"""Pure literal quotation checks; never infer meaning or repair a quote."""

def locate_quote(text: str, quote: str, start_line: int) -> tuple[int,int]:
    if not isinstance(quote,str) or not 12<=len(quote)<=240:
        raise ValueError('引文须为12至240字符的连续原文。')
    offset=text.find(quote)
    if offset<0:raise ValueError('引文不在本轮实际返回的连续原文中。')
    first=start_line+text[:offset].count('\n')
    return first,first+quote.count('\n')
