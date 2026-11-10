import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useTaskFeed } from '@/hooks/use-task-feed';
import { api } from '@/lib/api';

vi.mock('@/lib/api', () => ({api:vi.fn(), ApiError:class extends Error {status=500;}}));
afterEach(() => {vi.useRealTimers();vi.unstubAllGlobals();vi.clearAllMocks();});

it('falls back without overlapping a pending initial task request', async () => {
  vi.useFakeTimers();
  let finish!: (value: {tasks: []}) => void;
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => {finish=resolve;}));
  vi.mocked(api).mockResolvedValue({tasks:[]});
  let source!: FakeSource;
  class FakeSource {
    onerror!: () => void; onopen=null; onmessage=null; close=vi.fn();
    constructor(){source=this;}
  }
  vi.stubGlobal('EventSource', FakeSource);
  const receive=vi.fn();
  const hook=renderHook(() => useTaskFeed(true,receive,vi.fn()));
  expect(api).toHaveBeenCalledTimes(1);
  act(() => source.onerror());
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => {finish({tasks:[]});});
  expect(receive).toHaveBeenCalledTimes(1);
  await act(async () => {await vi.advanceTimersByTimeAsync(1500);});
  expect(api).toHaveBeenCalledTimes(2);
  hook.unmount();
  await vi.advanceTimersByTimeAsync(10000);
  expect(api).toHaveBeenCalledTimes(2);
});
