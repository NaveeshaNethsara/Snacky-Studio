import { describe, expect, it } from 'vitest';
import { mergeTasks, pendingSaves, persistSaves } from '@/lib/tasks';
import type { Task } from '@/types';
const task = (id:string, status:Task['status'], updated_at:number):Task => ({id,status,updated_at,created_at:1,url:'https://youtu.be/test',format:'mp4',quality:'720',title:'Example',progress:5,downloaded_bytes:5,total_bytes:100,speed:'1 MB/s',eta:'5s'});
describe('independent tasks', () => {
  it('does not regress a newer completed task when an old snapshot arrives', () => {
    const current=task('one','completed',3);
    const merged = mergeTasks([current],[task('one','downloading',2),task('two','downloading',4)]);
    expect(merged).toHaveLength(2);
    expect(merged.find(value => value.id === 'one')).toEqual(current);
    expect(merged.find(value => value.id === 'two')).toEqual(task('two','downloading',4));
  });
  it('retains active tasks when many completed jobs arrive', () => {
    const active=task('active','downloading',1);
    expect(mergeTasks([active],Array.from({length:30},(_,i)=>task(String(i),'completed',2))).some(t=>t.id==='active')).toBe(true);
  });
  it('persists valid pending save intentions across refresh', () => {
    const id='11111111-1111-4111-8111-111111111111';
    persistSaves(new Set([id])); expect(pendingSaves().has(id)).toBe(true);
    sessionStorage.setItem('snacky.browserWanted','["bad",true]');expect(pendingSaves().size).toBe(0);
  });
});
