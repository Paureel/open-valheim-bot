using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
namespace ValheimCodexBridge
{
    // Adapted from ValheimMCP's dispatcher. Expired work must NOT execute later.
    public sealed class MainThreadDispatcher
    {
        sealed class Work
        {
            public Func<object> Run;
            public long Deadline;
            public int Generation;
            public readonly TaskCompletionSource<object> Done = new TaskCompletionSource<object>(TaskCreationOptions.RunContinuationsAsynchronously);
        }
        readonly ConcurrentQueue<Work> queue = new ConcurrentQueue<Work>();
        int count, generation;
        public static long Now => Stopwatch.GetTimestamp();
        public static long Ms(int ms) => (long)(ms * (double)Stopwatch.Frequency / 1000);
        public object Invoke(Func<object> run, int timeoutMs = 2000)
        {
            if (Interlocked.Increment(ref count) > 32) { Interlocked.Decrement(ref count); throw new InvalidOperationException("Main-thread queue full"); }
            var work = new Work { Run = run, Deadline = Now + Ms(timeoutMs), Generation = Volatile.Read(ref generation) };
            queue.Enqueue(work);
            if (!work.Done.Task.Wait(timeoutMs)) throw new TimeoutException("Game did not process request before its deadline");
            return work.Done.Task.GetAwaiter().GetResult();
        }
        public void CancelPending() => Interlocked.Increment(ref generation);
        public void Pump()
        {
            // Bound frame work; no event handles disposed while a queued action still owns them.
            for (int n = 0; n < 8 && queue.TryDequeue(out var work); n++)
            {
                Interlocked.Decrement(ref count);
                if (Now >= work.Deadline || work.Generation != Volatile.Read(ref generation))
                { work.Done.TrySetException(new TimeoutException("Request expired or was cancelled by stop")); continue; }
                try { work.Done.TrySetResult(work.Run()); }
                catch (Exception e) { work.Done.TrySetException(e); }
            }
        }
    }
}
