import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as flush } from "node:timers/promises";
import { startNotificationPolling } from "../src/notifications.js";


function harness(load, canPoll = () => true) {
  const scheduled = new Map();
  let nextId = 0;
  const received = [];
  const errors = [];
  const polling = startNotificationPolling({
    load,
    canPoll,
    onData: (data) => received.push(data),
    onError: (error) => errors.push(error),
    setTimer: (callback, delay) => {
      const id = ++nextId;
      scheduled.set(id, { callback, delay });
      return id;
    },
    clearTimer: (id) => scheduled.delete(id),
  });
  return {
    ...polling, received, errors,
    delay: () => [...scheduled.values()][0]?.delay,
    tick: async () => {
      assert.equal(scheduled.size, 1);
      await [...scheduled.values()][0].callback();
    },
  };
}

test("delivers new inbox snapshots and schedules a single follow-up", async () => {
  let deliveries = 0;
  const session = harness(async () => ({ unread_count: deliveries++ }));
  await flush();
  assert.deepEqual(session.received, [{ unread_count: 0 }]);
  assert.equal(session.delay(), 30_000);
  await session.tick();
  assert.deepEqual(session.received.at(-1), { unread_count: 1 });
  session.stop();
  assert.equal(session.delay(), undefined);
});

test("backs off on repeated failures and resets after reconnecting", async () => {
  let connected = false;
  const session = harness(async () => {
    if (!connected) throw Error("Network unavailable");
    return "latest snapshot";
  });
  await flush();
  for (const expected of [5_000, 10_000, 20_000, 40_000, 80_000, 120_000, 120_000]) {
    assert.equal(session.delay(), expected);
    await session.tick();
  }
  assert.equal(session.errors.length, 8);
  connected = true;
  session.resync();
  await flush();
  assert.deepEqual(session.received, ["latest snapshot"]);
  assert.equal(session.delay(), 30_000);
  session.stop();
});

test("aborts offline or superseded requests and ignores late responses", async () => {
  let connected = true;
  const pending = [];
  const session = harness((signal) => new Promise((resolve) => pending.push({ signal, resolve })), () => connected);
  session.resync();
  assert.equal(pending.length, 1);
  connected = false;
  session.resync();
  assert.equal(pending[0].signal.aborted, true);
  assert.equal(session.delay(), undefined);
  connected = true;
  session.resync();
  pending[1].resolve("current account snapshot");
  pending[0].resolve("superseded snapshot");
  await flush();
  assert.deepEqual(session.received, ["current account snapshot"]);
  assert.equal(session.delay(), 30_000);
  session.stop();
});
