// webrtc.js — звонки
let localStream = null;
let peerConnection = null;
let currentCallUser = null;
const rtcConfig = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] };

async function startCall(u) {
    currentCallUser = u;
    try {
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        peerConnection = new RTCPeerConnection(rtcConfig);
        localStream.getTracks().forEach(t => peerConnection.addTrack(t, localStream));
        peerConnection.onicecandidate = (e) => { if (e.candidate) socket.emit('call_signal', { to: u, ice: e.candidate }); };
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);
        socket.emit('call_user', { to: u, sdp: offer });
        showToast('📞 Звоним @' + u, 'info');
    } catch (e) {
        showToast('Ошибка микрофона', 'error');
        console.error('startCall error:', e);
    }
}

function hangUp() {
    if (peerConnection) { peerConnection.close();
        peerConnection = null; }
    if (localStream) { localStream.getTracks().forEach(t => t.stop());
        localStream = null; }
    currentCallUser = null;
}

socket.on('incoming_call', async (d) => {
    if (confirm('📞 @' + d.from + ' звонит! Принять?')) {
        currentCallUser = d.from;
        try {
            localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            peerConnection = new RTCPeerConnection(rtcConfig);
            localStream.getTracks().forEach(t => peerConnection.addTrack(t, localStream));
            peerConnection.onicecandidate = (e) => { if (e.candidate) socket.emit('call_signal', { to: d.from, ice: e.candidate }); };
            await peerConnection.setRemoteDescription(new RTCSessionDescription(d.sdp));
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);
            socket.emit('call_accepted', { to: d.from, sdp: answer });
        } catch (e) { console.error('incoming_call error:', e);
            hangUp(); }
    } else {
        socket.emit('call_rejected', { to: d.from });
    }
});

socket.on('call_accepted', async (d) => {
    try { await peerConnection.setRemoteDescription(new RTCSessionDescription(d.sdp));
        showToast('📞 Соединение установлено!', 'success'); } catch (e) { console.error('call_accepted error:', e); }
});

socket.on('call_signal', (d) => {
    if (d.ice && peerConnection) peerConnection.addIceCandidate(new RTCIceCandidate(d.ice)).catch(console.error);
});
