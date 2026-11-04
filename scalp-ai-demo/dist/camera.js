/* Optional browser camera/UVC microscope capture. Permission starts with a click. */
(() => {
  'use strict';
  let active = null;
  const markup = () => `<section class="camera-panel" data-scalp-camera aria-labelledby="camera-heading">
    <div class="camera-heading"><div><p class="section-kicker">직접 촬영하기</p><h3 id="camera-heading">두피 현미경이나 카메라를 연결해 보세요</h3></div><span class="camera-badge">실시간 미리보기</span></div>
    <p class="camera-description">USB 현미경을 연결한 뒤 카메라 연결을 누르세요. 브라우저가 카메라로 인식하는 장치를 사용할 수 있어요.</p>
    <div class="camera-preview" data-camera-preview>
      <div class="camera-placeholder" data-camera-idle><span class="camera-placeholder-icon" aria-hidden="true">◎</span><strong>촬영할 두피를 화면 가운데에 맞춰 주세요</strong><span>연결하면 이곳에 실시간 영상이 나타나요.</span></div>
      <video data-camera-video autoplay muted playsinline aria-label="두피 촬영 실시간 미리보기" hidden></video>
      <div class="camera-frame" data-camera-frame hidden aria-hidden="true"><span>초점과 빛 반사를 확인해 주세요</span></div>
    </div>
    <div class="camera-controls"><button type="button" class="button secondary" data-camera-action="start">카메라 연결</button><label class="camera-device-label">촬영 장치<select data-camera-device aria-label="촬영 장치 선택" disabled><option value="">연결 후 장치를 선택할 수 있어요</option></select></label><button type="button" class="button" data-camera-action="capture" disabled>이 화면 촬영하기</button><button type="button" class="text-button" data-camera-action="stop" hidden>연결 해제</button></div>
    <p class="camera-status" data-camera-status role="status" aria-live="polite">연결 버튼을 누를 때만 카메라 사용 권한을 요청해요.</p>
    <p class="camera-privacy">실시간 영상은 이 기기에서만 표시해요. 촬영한 사진은 선택 목록에 추가되며, 분석 버튼을 누르기 전까지 전송하지 않아요. 장치 전용 프로그램만 지원하는 현미경은 사진 파일로 추가해 주세요.</p>
  </section>`;

  function stop() {
    if (active) active.dispose();
    active = null;
  }
  function mount({ onCapture, onMessage = () => {} } = {}) {
    stop();
    const root = document.querySelector('[data-scalp-camera]');
    if (!root) return () => {};
    const video = root.querySelector('[data-camera-video]');
    const idle = root.querySelector('[data-camera-idle]');
    const frame = root.querySelector('[data-camera-frame]');
    const status = root.querySelector('[data-camera-status]');
    const startButton = root.querySelector('[data-camera-action="start"]');
    const captureButton = root.querySelector('[data-camera-action="capture"]');
    const stopButton = root.querySelector('[data-camera-action="stop"]');
    const deviceSelect = root.querySelector('[data-camera-device]');
    let stream = null, generation = 0, disposed = false, busy = false, capturing = false;
    const media = navigator.mediaDevices;
    const supported = !!(media && typeof media.getUserMedia === 'function');
    const listeners = [];
    const listen = (target, type, handler) => {
      target.addEventListener(type, handler);
      listeners.push(() => target.removeEventListener(type, handler));
    };
    const message = (text, error = false) => {
      if (disposed) return;
      status.textContent = text;
      status.classList.toggle('is-error', error);
      if (error) onMessage(text);
    };
    const release = () => {
      const previous = stream;
      stream = null;
      video.srcObject = null;
      if (previous) previous.getTracks().forEach(track => track.stop());
      video.hidden = true;
      frame.hidden = true;
      idle.hidden = false;
    };
    const update = () => {
      if (disposed) return;
      const live = !!stream?.active;
      startButton.disabled = busy || !supported;
      startButton.textContent = busy ? '연결하고 있어요…' : live ? '다시 연결하기' : '카메라 연결';
      captureButton.disabled = !live || !video.videoWidth || busy || capturing;
      captureButton.textContent = capturing ? '사진을 준비하고 있어요…' : '이 화면 촬영하기';
      stopButton.hidden = !live && !busy;
      deviceSelect.disabled = busy || !live;
    };
    const deviceOptions = async () => {
      if (!media?.enumerateDevices || disposed || !stream) return;
      const request = generation;
      try {
        const devices = (await media.enumerateDevices()).filter(device => device.kind === 'videoinput');
        if (disposed || request !== generation || !stream) return;
        const selected = stream.getVideoTracks()[0]?.getSettings?.().deviceId;
        deviceSelect.replaceChildren(...devices.map((device, index) => new Option(device.label || `카메라 ${index + 1}`, device.deviceId)));
        if (!devices.length) deviceSelect.add(new Option('현재 연결한 카메라', ''));
        if (selected) deviceSelect.value = selected;
      } catch {
        message('영상은 연결됐어요. 장치 목록을 다시 확인하려면 카메라를 다시 연결해 주세요.');
      }
    };
    const errorMessage = error => {
      if (['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(error?.name)) return '카메라 사용이 허용되지 않았어요. 브라우저의 주소창 옆 권한 설정에서 카메라를 허용한 뒤 다시 연결해 주세요.';
      if (['NotFoundError', 'DevicesNotFoundError'].includes(error?.name)) return '연결된 카메라를 찾지 못했어요. 두피 현미경의 USB 연결을 확인하거나 사진 파일을 추가해 주세요.';
      if (['NotReadableError', 'TrackStartError'].includes(error?.name)) return '카메라 영상을 열지 못했어요. 현미경 전용 프로그램이나 다른 앱의 카메라 사용을 종료한 뒤 다시 시도해 주세요.';
      if (['OverconstrainedError', 'ConstraintNotSatisfiedError'].includes(error?.name)) return '선택한 촬영 장치를 사용할 수 없어요. USB 연결을 확인한 뒤 카메라를 다시 연결해 주세요.';
      return '카메라에 연결하지 못했어요. 연결 상태와 브라우저 권한을 확인하거나 사진 파일을 추가해 주세요.';
    };
    const connect = async deviceId => {
      const request = ++generation;
      release();
      busy = true;
      update();
      message('브라우저의 카메라 권한 요청을 확인해 주세요.');
      try {
        const constraints = { audio: false, video: deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: 'environment' } } };
        const acquired = await media.getUserMedia(constraints);
        if (disposed || request !== generation) {
          acquired.getTracks().forEach(track => track.stop());
          return;
        }
        stream = acquired;
        const track = stream.getVideoTracks()[0];
        if (!track) throw new Error('No video track');
        track.addEventListener('ended', () => {
          if (disposed || request !== generation) return;
          ++generation;
          busy = false;
          release();
          update();
          message('촬영 장치의 연결이 끊겼어요. USB 연결을 확인한 뒤 다시 연결해 주세요.', true);
        }, { once: true });
        video.srcObject = stream;
        video.hidden = false;
        idle.hidden = true;
        frame.hidden = false;
        await video.play();
        if (disposed || request !== generation) return;
        message('실시간 영상이 연결됐어요. 두피가 선명하게 보이면 이 화면 촬영하기를 눌러 주세요.');
        await deviceOptions();
      } catch (error) {
        if (disposed || request !== generation) return;
        release();
        message(errorMessage(error), true);
      } finally {
        if (!disposed && request === generation) {
          busy = false;
          update();
        }
      }
    };
    const capture = async () => {
      if (disposed || !stream?.active || !video.videoWidth || capturing) return;
      capturing = true;
      update();
      try {
        const canvas = document.createElement('canvas');
        const scale = Math.min(1, 2560 / Math.max(video.videoWidth, video.videoHeight));
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
        canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
        const context = canvas.getContext('2d');
        if (!context) throw new Error('Canvas unavailable');
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92));
        if (!blob) throw new Error('Capture unavailable');
        if (disposed) return;
        const file = new File([blob], `두피촬영-${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`, { type: 'image/jpeg', lastModified: Date.now() });
        const accepted = typeof onCapture === 'function' ? await onCapture(file) : false;
        if (!disposed && accepted !== false) message('촬영한 사진을 선택 목록에 추가했어요. 목록에서 사진을 확인해 주세요.');
      } catch {
        message('사진을 촬영하지 못했어요. 영상이 선명하게 보이는지 확인한 뒤 다시 시도해 주세요.', true);
      } finally {
        capturing = false;
        update();
      }
    };
    const disconnect = () => {
      ++generation;
      busy = false;
      release();
      update();
      message('카메라 연결을 해제했어요. 촬영한 사진은 선택 목록에서 확인할 수 있어요.');
    };
    const dispose = () => {
      if (disposed) return;
      disposed = true;
      ++generation;
      release();
      listeners.forEach(remove => remove());
      if (active?.dispose === dispose) active = null;
    };
    listen(startButton, 'click', () => connect());
    listen(stopButton, 'click', disconnect);
    listen(captureButton, 'click', capture);
    listen(deviceSelect, 'change', () => connect(deviceSelect.value || undefined));
    listen(video, 'loadedmetadata', update);
    listen(video, 'canplay', update);
    listen(window, 'pagehide', dispose);
    if (media?.addEventListener) listen(media, 'devicechange', deviceOptions);
    if (!supported) {
      message(window.isSecureContext ? '이 브라우저에서는 카메라 미리보기를 사용할 수 없어요. Chrome·Edge에서 열거나 사진 파일을 추가해 주세요.' : '카메라 촬영은 보안 연결(HTTPS) 또는 이 PC의 서비스 주소에서 사용할 수 있어요. 사진 파일 추가는 계속 이용할 수 있어요.', true);
    }
    update();
    active = { dispose };
    return dispose;
  }
  window.ScalpCamera = Object.freeze({ markup, mount, stop });
})();
