import {test} from 'node:test';
import assert from 'node:assert/strict';
import {locateOriginal,highlightText} from '../src/source-links.ts';
test('code point columns convert to UTF16 and preserve old whole lines',()=>{
  assert.deepEqual(locateOriginal('甲😀乙丙',1,1,'😀乙',1,3),{from:{line:0,ch:1},to:{line:0,ch:4}});
  assert.deepEqual(locateOriginal('甲\r\n乙',2,2,'乙'),{from:{line:1,ch:0},to:{line:1,ch:1}});
  assert.throws(()=>locateOriginal('甲😀乙',1,1,'错',1,2));
  assert.throws(()=>locateOriginal('甲😀乙',1,1,'甲',-1,1));
  assert.throws(()=>locateOriginal('甲😀乙',1,1,'甲',0,99));
});
test('page highlight reconstructs partial lines without duplicate body',()=>{
  assert.equal(highlightText({text:'😀乙',start_line:1,start_col:1,highlight_start_line:1,highlight_end_line:1,highlight_start_col:1,highlight_end_col:3}),'😀乙');
});
