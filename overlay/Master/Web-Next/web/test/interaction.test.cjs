const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function fixture() {
  const handlers = {};
  const sent = [];
  const tracks = [{ stopped: false, stop() { this.stopped = true; } }];
  const peers = [];
  const intervals = [];
  let seq = 0;
  class Peer {
    constructor() { this.connectionState = 'new'; this.iceGatheringState = 'complete'; this.localDescription = { sdp: 'offer-sdp' }; this.listeners = {}; peers.push(this); }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    removeEventListener(name) { delete this.listeners[name]; }
    connected() { this.connectionState = 'connected'; if (this.onconnectionstatechange) this.onconnectionstatechange(); if (this.listeners.connectionstatechange) this.listeners.connectionstatechange(); }
    addTrack() {}
    addTransceiver() {}
    async createOffer() { return { type: 'offer', sdp: 'offer-sdp' }; }
    async setLocalDescription() {}
    async setRemoteDescription() {}
    close() { this.closed = true; }
  }
  const window = {
    isSecureContext: true,
    crypto: { randomUUID: () => `request-${++seq}` },
    navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => tracks }) } },
    RTCPeerConnection: Peer,
    C50C: { Store: { on(name, fn) { (handlers[name] ||= []).push(fn); } }, WS: { send(msg) { sent.push(msg); return true; } } },
    setTimeout, clearTimeout,
    setInterval(fn) { intervals.push(fn); return fn; }, clearInterval() {},
  };
  vm.runInNewContext(fs.readFileSync('Master/Web-Next/web/js/interaction.js', 'utf8'), { window });
  const client = window.C50C.Interaction.create({ onState() {}, onTrack() {} });
  function reply(request, data) { for (const f of handlers.interaction_reply) f({ request_id: request.request_id, ok: true, data }); }
  async function tick() { await new Promise(resolve => setImmediate(resolve)); }
  async function activate() { await tick(); peers[0].connected(); await tick(); assert.equal(sent[2].action, 'activate'); reply(sent[2], {}); }
  return { client, sent, tracks, peers, reply, tick, handlers, window, intervals, activate };
}

test('cancelled create is deleted when its late response arrives', async () => {
  const f = fixture();
  const start = f.client.startAudio('remote_announcement');
  await f.tick();
  assert.equal(f.sent[0].action, 'create');
  f.client.stopAudio();
  f.reply(f.sent[0], { session_id: 'late-session' });
  await f.tick();
  assert.equal(f.sent[1].action, 'delete');
  assert.equal(f.sent[1].session_id, 'late-session');
  f.reply(f.sent[1], {});
  await start;
  assert.equal(f.tracks[0].stopped, true);
});

test('announcement sends an offer and releases media on stop', async () => {
  const f = fixture();
  const start = f.client.startAudio('remote_announcement');
  await f.tick();
  f.reply(f.sent[0], { session_id: 'session-1' });
  await f.tick();
  assert.equal(f.sent[1].action, 'offer');
  assert.equal(f.sent[1].kind, 'publish');
  assert.equal(f.sent[1].sdp, 'offer-sdp');
  f.reply(f.sent[1], { type: 'answer', sdp: 'answer-sdp' });
  await f.activate();
  await start;
  f.client.stopAudio();
  assert.equal(f.peers[0].closed, true);
  assert.equal(f.tracks[0].stopped, true);
  assert.equal(f.sent[3].action, 'delete');
  f.reply(f.sent[3], {});
});

test('intercom negotiates publish and microphone and closes on disconnect', async () => {
  const f = fixture();
  const start = f.client.startAudio('intercom');
  await f.tick();
  f.reply(f.sent[0], { session_id: 'session-2' });
  await f.tick();
  f.reply(f.sent[1], { type: 'answer', sdp: 'a' });
  await f.activate();
  await f.tick();
  assert.equal(f.sent[3].kind, 'microphone');
  f.reply(f.sent[3], { type: 'answer', sdp: 'b' });
  await start;
  for (const fn of f.handlers.ws_close) fn();
  assert.equal(f.tracks[0].stopped, true);
  assert.ok(f.peers.every(peer => peer.closed));
});

test('video is receive only and can run without microphone access', async () => {
  const f = fixture();
  f.window.navigator.mediaDevices.getUserMedia = () => { throw new Error('unexpected capture'); };
  const start = f.client.startVideo();
  assert.equal(f.sent[0].mode, 'video');
  f.reply(f.sent[0], { session_id: 'video-1' });
  await f.tick();
  assert.equal(f.sent[1].kind, 'camera');
  f.reply(f.sent[1], { type: 'answer', sdp: 'a' });
  await start;
  f.client.stopVideo();
  assert.equal(f.peers[0].closed, true);
  f.reply(f.sent[2], {});
});


test('preemption closes the active audio session', async () => {
  const f = fixture();
  const start = f.client.startAudio('remote_announcement');
  await f.tick();
  f.reply(f.sent[0], { session_id: 'session-3' });
  await f.tick();
  f.reply(f.sent[1], { type: 'answer', sdp: 'a' });
  await f.activate();
  await start;
  const poll = f.intervals[0]();
  assert.equal(f.sent[3].action, 'status');
  f.reply(f.sent[3], { available: true, owner: { request_id: 'sos-1', source: 'sos' }, playback_state: 'playing', capabilities: {} });
  await poll;
  assert.equal(f.tracks[0].stopped, true);
  assert.equal(f.peers[0].closed, true);
  assert.equal(f.sent[4].action, 'delete');
  f.reply(f.sent[4], {});
});

test('failed authentication stops local media immediately', async () => {
  const f = fixture();
  const start = f.client.startAudio('remote_announcement');
  await f.tick();
  f.reply(f.sent[0], { session_id: 'session-4' });
  await f.tick();
  f.reply(f.sent[1], { type: 'answer', sdp: 'a' });
  await f.activate();
  await start;
  for (const fn of f.handlers.auth) fn({ ok: false });
  assert.equal(f.tracks[0].stopped, true);
  assert.equal(f.peers[0].closed, true);
  f.reply(f.sent[3], {});
});


test('failed playback status closes the audio session', async () => {
  const f = fixture();
  const start = f.client.startAudio('remote_announcement');
  await f.tick();
  f.reply(f.sent[0], { session_id: 'session-5' });
  await f.tick();
  f.reply(f.sent[1], { type: 'answer', sdp: 'a' });
  await f.activate();
  await start;
  const poll = f.intervals[0]();
  f.reply(f.sent[3], { available: true, owner: { request_id: 'session-5', source: 'remote_announcement' }, playback_state: 'failed', capabilities: {} });
  await poll;
  assert.equal(f.tracks[0].stopped, true);
  assert.equal(f.peers[0].closed, true);
  f.reply(f.sent[4], {});
});

test('track without stream is attached to a new media stream', async () => {
  const f = fixture();
  let received;
  f.window.MediaStream = class { constructor(tracks) { this.tracks = tracks; } };
  const callbacks = {};
  f.client = f.window.C50C.Interaction.create({ onState() {}, onTrack(kind, stream) { callbacks[kind] = stream; } });
  const start = f.client.startVideo();
  f.reply(f.sent[0], { session_id: 'video-2' });
  await f.tick();
  f.reply(f.sent[1], { type: 'answer', sdp: 'a' });
  await start;
  const track = { kind: 'video' };
  f.peers[0].ontrack({ track, streams: [] });
  received = callbacks.camera;
  assert.equal(received.tracks[0], track);
  f.client.stopVideo();
  f.reply(f.sent[2], {});
});


test('activation waits for publishing connection and cancellation releases it', async () => {
  const f = fixture();
  const start = f.client.startAudio('remote_announcement');
  await f.tick();
  f.reply(f.sent[0], { session_id: 'session-wait' });
  await f.tick();
  f.reply(f.sent[1], { type: 'answer', sdp: 'a' });
  await f.tick();
  assert.equal(f.sent.length, 2);
  f.client.stopAudio();
  assert.equal(f.sent[2].action, 'delete');
  f.reply(f.sent[2], {});
  await start;
  assert.equal(f.peers[0].closed, true);
});

test('publishing connection sends activation before microphone offer', async () => {
  const f = fixture();
  const start = f.client.startAudio('intercom');
  await f.tick();
  f.reply(f.sent[0], { session_id: 'session-activate' });
  await f.tick();
  f.reply(f.sent[1], { type: 'answer', sdp: 'a' });
  await f.tick();
  f.peers[0].connected();
  await f.tick();
  assert.equal(f.sent[2].action, 'activate');
  f.reply(f.sent[2], {});
  await f.tick();
  assert.equal(f.sent[3].kind, 'microphone');
  f.reply(f.sent[3], { type: 'answer', sdp: 'b' });
  await start;
  f.client.stopAudio();
  f.reply(f.sent[4], {});
});
