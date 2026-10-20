"""Versioned heading sections with non-overlapping original character ranges."""
from datetime import date
import re

SCHEMA_VERSION=1
PARSER_VERSION=2
FULL=re.compile(r'(?<!\d)(20\d{2})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})\s*日?(?!\d)')
PART=re.compile(r'(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?')


def normalized_text(text):
    return '\n'.join(text.splitlines())


def position(text, offset):
    """1-based line, 0-based Unicode code-point column, exclusive end."""
    return text.count('\n',0,offset)+1,offset-(text.rfind('\n',0,offset)+1)


def heading_date(title, ancestors):
    full=list(FULL.finditer(title));partial=[m for m in PART.finditer(title) if not any(f.start()<=m.start() and m.end()<=f.end() for f in full)]
    inherited=next((r for r in reversed(ancestors) if r['date_status']!='undated'),None)
    year_match=re.fullmatch(r'\s*(20\d{2})\s*年\s*',title)
    year=int(year_match[1]) if year_match else next((r['year'] for r in reversed(ancestors) if r.get('year')),None)
    label=None;status='undated'
    if full or partial:
        if len(full)+len(partial)>1 or re.search(r'(?:至|到|[～~—–])',title) or (full and re.match(r'\s*-\s*\d',title[full[0].end():])):
            status='ambiguous'
        else:
            parts=tuple(map(int,full[0].groups())) if full else ((year,)+tuple(map(int,partial[0].groups())))
            try:
                if parts[0] is None:raise ValueError()
                label=date(*parts).isoformat();status='dated'
            except (ValueError,TypeError):status='ambiguous'
    elif re.search(r'\d\s*(?:月|[-/.])\s*\d',title):status='ambiguous'
    elif inherited:label,status=inherited['heading_date'],inherited['date_status']
    return dict(heading_date=label,date_status=status,year=year)


def parse_sections(text):
    text=normalized_text(text);lines=text.splitlines(keepends=True);offset=0;start=0;stack=[];result=[];fenced=None
    if lines and lines[0].strip()=='---':
        for i,line in enumerate(lines[1:],1):
            if line.strip()=='---':start=sum(map(len,lines[:i+1]));break
    section_start=start;current=dict(heading='',heading_date=None,date_status='undated')
    def flush(end):
        body=text[section_start:end].rstrip('\n')
        if not any(l.strip() and not re.match(r'^#{1,6}\s+',l) for l in body.splitlines()):return
        a,b=section_start,section_start+len(body);sl,sc=position(text,a);el,ec=position(text,b)
        result.append(dict(current,start_offset=a,end_offset=b,start_line=sl,start_col=sc,end_line=el,end_col=ec,text=body))
    for line in lines:
        here=offset;offset+=len(line)
        if here<start:continue
        fence=re.match(r'^\s{0,3}(`{3,}|~{3,})',line)
        if fence:
            marker=fence[1][0]
            if fenced is None:fenced=(marker,len(fence[1]))
            elif fenced[0]==marker and len(fence[1])>=fenced[1] and re.fullmatch(r'\s{0,3}'+re.escape(marker)+r'{'+str(fenced[1])+r',}\s*',line):fenced=None
            continue
        match=re.match(r'^(#{1,6})\s+(.+?)\s*$',line) if fenced is None else None
        if match:
            flush(here);level=len(match[1]);stack=[r for r in stack if r['level']<level]
            info=heading_date(match[2],stack);stack.append(dict(level=level,title=match[2],**info))
            current=dict(heading=' / '.join(r['title'] for r in stack),heading_date=info['heading_date'],date_status=info['date_status'])
            section_start=here
    flush(len(text));return result


def create_schema(con):
    con.executescript('''
    CREATE TABLE research_sections(id INTEGER PRIMARY KEY,path TEXT,heading TEXT,heading_date TEXT,date_status TEXT,start_line INTEGER,end_line INTEGER,start_offset INTEGER,end_offset INTEGER);
    CREATE TABLE research_spans(id INTEGER PRIMARY KEY,section_id INTEGER,chunk_id INTEGER,start_offset INTEGER,end_offset INTEGER,text TEXT);
    CREATE INDEX research_section_paths ON research_sections(path,heading_date);
    ''')
    con.execute('INSERT INTO meta VALUES (?,?)',('research_schema_version',str(SCHEMA_VERSION)))
    con.execute('INSERT INTO meta VALUES (?,?)',('research_parser_version',str(PARSER_VERSION)))


def catalog_schema_version(con):
    try:
        row=con.execute("SELECT value FROM meta WHERE key='research_schema_version'").fetchone()
        parser=con.execute("SELECT value FROM meta WHERE key='research_parser_version'").fetchone()
        return int(row[0]) if row and parser and int(parser[0])==PARSER_VERSION else 0
    except Exception:return 0


def build_catalog(con,path,text,chunk_rows):
    text=normalized_text(text);line_offsets=[0]
    for m in re.finditer('\n',text):line_offsets.append(m.end())
    for section in parse_sections(text):
        cur=con.execute('INSERT INTO research_sections(path,heading,heading_date,date_status,start_line,end_line,start_offset,end_offset) VALUES (?,?,?,?,?,?,?,?)',tuple([path]+[section[k] for k in ('heading','heading_date','date_status','start_line','end_line','start_offset','end_offset')]))
        sid=cur.lastrowid
        # Partition a section without dropping the newlines between old chunks.
        cuts=[section['start_offset']]+sorted({line_offsets[r['start_line']-1] for r in chunk_rows if section['start_offset']<line_offsets[r['start_line']-1]<section['end_offset']})+[section['end_offset']]
        for a,b in zip(cuts,cuts[1:]):
            row=next((r for r in chunk_rows if line_offsets[r['start_line']-1]<=a and r['end_line']>=position(text,a)[0]),None)
            con.execute('INSERT INTO research_spans(section_id,chunk_id,start_offset,end_offset,text) VALUES (?,?,?,?,?)',(sid,row['id'] if row else None,a,b,text[a:b]))


def enumerate_sections(con,allowed_paths,date_from=None,date_to=None):
    if catalog_schema_version(con)!=SCHEMA_VERSION:raise ValueError('REINDEX_REQUIRED')
    rows=[dict(r) for r in con.execute('SELECT * FROM research_sections ORDER BY heading_date,path,start_line,id') if r['path'] in allowed_paths and (r['date_status']!='dated' or ((not date_from or r['heading_date']>=date_from) and (not date_to or r['heading_date']<=date_to)))]
    rows.sort(key=lambda r:(r['date_status']!='dated',r['heading_date'] or '',r['path'],r['start_line'],r['id']))
    for row in rows:
        row['section_id']=str(row['id']);row['span_count']=con.execute('SELECT count(*) FROM research_spans WHERE section_id=?',(row['id'],)).fetchone()[0]
    return rows
