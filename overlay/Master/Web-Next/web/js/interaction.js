(function () {
  'use strict';
  var C = window.C50C;

  function create(options) {
    var pending = new Map();
    var lateCreates = new Set();
    var audio = null;
    var video = null;

    function request(action, fields) {
      var id = window.crypto.randomUUID();
      var message = Object.assign({ t: 'interaction', request_id: id, action: action }, fields);
      return new Promise(function (resolve, reject) {
        var timer = window.setTimeout(function () {
          pending.delete(id);
          if (action === 'create') lateCreates.add(id);
          reject(new Error('音视频请求超时'));
        }, 15000);
        pending.set(id, { resolve: resolve, reject: reject, timer: timer, action: action });
        if (!C.WS.send(message)) {
          window.clearTimeout(timer);
          pending.delete(id);
          reject(new Error('控制连接已断开'));
        }
      });
    }

    function discard(sessionId) {
      request('delete', { session_id: sessionId }).catch(function (error) {
        options.onState('error', error.message);
      });
    }

    C.Store.on('interaction_reply', function (reply) {
      var entry = pending.get(reply.request_id);
      if (!entry) {
        if (lateCreates.delete(reply.request_id) && reply.ok && reply.data && reply.data.session_id) {
          discard(reply.data.session_id);
        }
        return;
      }
      pending.delete(reply.request_id);
      window.clearTimeout(entry.timer);
      if (reply.ok) entry.resolve(reply.data);
      else entry.reject(new Error(reply.message));
    });

    function stop(session, type) {
      if (!session || session.cancelled) return;
      session.cancelled = true;
      if (session.poll) window.clearInterval(session.poll);
      session.iceCancels.forEach(function (cancel) { cancel(); });
      session.peers.forEach(function (peer) { peer.close(); });
      if (session.stream) session.stream.getTracks().forEach(function (track) { track.stop(); });
      if (session.id) discard(session.id);
      if (type === 'audio' && audio === session) audio = null;
      if (type === 'video' && video === session) video = null;
      options.onState(type, '已结束');
    }

    function waitIce(peer, session) {
      if (peer.iceGatheringState === 'complete') return Promise.resolve();
      return new Promise(function (resolve, reject) {
        var timer = window.setTimeout(function () { finish(new Error('ICE 收集超时')); }, 15000);
        function finish(error) {
          window.clearTimeout(timer);
          peer.removeEventListener('icegatheringstatechange', changed);
          session.iceCancels.delete(cancel);
          if (error) reject(error); else resolve();
        }
        function changed() { if (peer.iceGatheringState === 'complete') finish(); }
        function cancel() { finish(new Error('会话已结束')); }
        session.iceCancels.add(cancel);
        peer.addEventListener('icegatheringstatechange', changed);
      });
    }

    function waitConnected(peer, session) {
      if (peer.connectionState === 'connected') return Promise.resolve();
      return new Promise(function (resolve, reject) {
        var timer = window.setTimeout(function () { finish(new Error('媒体连接超时')); }, 15000);
        function finish(error) {
          window.clearTimeout(timer);
          peer.removeEventListener('connectionstatechange', changed);
          session.iceCancels.delete(cancel);
          if (error) reject(error); else resolve();
        }
        function changed() {
          if (peer.connectionState === 'connected') finish();
          else if (peer.connectionState === 'failed' || peer.connectionState === 'closed') finish(new Error('媒体连接失败'));
        }
        function cancel() { finish(new Error('会话已结束')); }
        session.iceCancels.add(cancel);
        peer.addEventListener('connectionstatechange', changed);
        changed();
      });
    }

    async function connect(session, kind) {
      var peer = new window.RTCPeerConnection();
      session.peers.push(peer);
      if (kind === 'publish') {
        session.stream.getTracks().forEach(function (track) { peer.addTransceiver(track, { direction: 'sendonly', streams: [session.stream] }); });
      } else {
        peer.addTransceiver(kind === 'camera' ? 'video' : 'audio', { direction: 'recvonly' });
        peer.ontrack = function (event) { if (!session.cancelled) options.onTrack(kind, new window.MediaStream([event.track])); };
      }
      peer.onconnectionstatechange = function () {
        if (!session.cancelled && peer.connectionState === 'connected') {
          var expected = session.mode === 'intercom' ? 2 : 1;
          if ((session.type === 'video' || session.activated) && session.peers.length === expected && session.peers.every(function (p) { return p.connectionState === 'connected'; })) {
            options.onState(session.type === 'video' ? 'camera' : 'audio', '媒体已连接');
          }
        }
        if (!session.cancelled && peer.connectionState === 'failed') {
          options.onState('error', '媒体连接失败');
          stop(session, session.type);
        }
      };
      await peer.setLocalDescription(await peer.createOffer());
      await waitIce(peer, session);
      if (session.cancelled) return;
      var answer = await request('offer', { session_id: session.id, kind: kind, sdp: peer.localDescription.sdp });
      if (!session.cancelled) await peer.setRemoteDescription(answer);
      if (kind === 'publish' && !session.cancelled) {
        await waitConnected(peer, session);
        if (session.cancelled) return;
        await request('activate', { session_id: session.id });
        if (!session.cancelled) {
          session.activated = true;
          if (session.mode !== 'intercom') options.onState('audio', '媒体已连接');
        }
      }
    }

    async function start(type, mode, capture) {
      if (!window.isSecureContext) throw new Error('音视频需要 HTTPS 安全上下文');
      if (!window.RTCPeerConnection || !window.crypto || !window.crypto.randomUUID) throw new Error('浏览器不支持音视频连接');
      if ((type === 'audio' && audio) || (type === 'video' && video)) throw new Error('会话已存在');
      var session = { type: type, mode: mode, activated: false, cancelled: false, peers: [], iceCancels: new Set(), stream: null, id: null, poll: null };
      if (type === 'audio') audio = session; else video = session;
      options.onState(type, '正在连接');
      try {
        if (capture) {
          if (!window.navigator.mediaDevices || !window.navigator.mediaDevices.getUserMedia) throw new Error('浏览器不支持麦克风采集');
          var streamPromise = window.navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
          session.stream = await streamPromise;
          if (session.cancelled) { session.stream.getTracks().forEach(function (track) { track.stop(); }); return; }
        }
        var created = await request('create', { mode: mode });
        session.id = created.session_id;
        if (session.cancelled) { discard(session.id); return; }
        if (capture) await connect(session, 'publish');
        if (!session.cancelled && mode === 'intercom') await connect(session, 'microphone');
        if (!session.cancelled && mode === 'video') await connect(session, 'camera');
        if (!session.cancelled && type === 'audio') {
          var checking = false;
          session.poll = window.setInterval(async function () {
            if (checking || session.cancelled) return;
            checking = true;
            try {
              var state = await request('status', {});
              if (!session.cancelled && (!state.owner || state.owner.request_id !== session.id || state.playback_state === 'failed' || state.playback_state === 'blocked')) {
                options.onState('error', '音频会话被抢占、结束或播放失败');
                stop(session, 'audio');
              }
            } catch (error) {
              if (!session.cancelled) { options.onState('error', error.message); stop(session, 'audio'); }
            } finally { checking = false; }
          }, 1000);
        }
      } catch (error) {
        if (!session.cancelled) { stop(session, type); throw error; }
      }
    }

    function stopAll() { stop(audio, 'audio'); stop(video, 'video'); }
    C.Store.on('ws_close', function () {
      stopAll();
      pending.forEach(function (entry) { window.clearTimeout(entry.timer); entry.reject(new Error('控制连接已断开')); });
      pending.clear();
      lateCreates.clear();
    });
    C.Store.on('auth', function (result) { if (!result.ok) stopAll(); });
    return {
      startAudio: function (mode) { return start('audio', mode, true); },
      startVideo: function () { return start('video', 'video', false); },
      stopAudio: function () { stop(audio, 'audio'); },
      stopVideo: function () { stop(video, 'video'); },
      stopAll: stopAll,
    };
  }
  C.Interaction = { create: create };
})();
