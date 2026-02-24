import './gesture-lock-panel.js';

export class GestureLockCancelledError extends Error {
  constructor(message = '手势验证已取消。') {
    super(message);
    this.name = 'GestureLockCancelledError';
  }
}

export class GestureLockTimeoutError extends Error {
  constructor(message = '手势验证超时。') {
    super(message);
    this.name = 'GestureLockTimeoutError';
  }
}

export function openGestureLock(options = {}) {
  const {
    endpoint = 'admin/verify',
    parent = document.body,
    autoRemove = true,
    timeout = 0,
    signal,
  } = options;

  if (!parent) {
    throw new Error('Gesture lock host元素不存在。');
  }

  const panel = document.createElement('gesture-lock-panel');
  panel.setAttribute('endpoint', endpoint);

  (parent.shadowRoot || parent).appendChild(panel);

  return new Promise((resolve, reject) => {
    let settled = false;
    let timeoutId;

    function cleanup() {
      panel.removeEventListener('gesture-lock-success', handleSuccess);
      panel.removeEventListener('gesture-lock-cancel', handleCancel);
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      if (signal) {
        signal.removeEventListener('abort', handleAbort);
      }
      if (autoRemove && panel.isConnected) {
        panel.remove();
      }
    }

    function settle(callback) {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      callback();
    }

    function handleSuccess(event) {
      settle(() => resolve(event.detail));
    }

    function handleCancel() {
      settle(() => reject(new GestureLockCancelledError()));
    }

    function handleAbort() {
      settle(() => reject(new GestureLockCancelledError('手势验证已被终止。')));
    }

    panel.addEventListener('gesture-lock-success', handleSuccess);
    panel.addEventListener('gesture-lock-cancel', handleCancel);

    if (signal) {
      if (signal.aborted) {
        handleAbort();
        return;
      }
      signal.addEventListener('abort', handleAbort, { once: true });
    }

    if (timeout > 0) {
      timeoutId = setTimeout(() => {
        settle(() => reject(new GestureLockTimeoutError()));
      }, timeout);
    }
  });
}

if (typeof window !== 'undefined') {
  window.GestureLock = window.GestureLock || {};
  window.GestureLock.openGestureLock = openGestureLock;
  window.GestureLock.GestureLockCancelledError = GestureLockCancelledError;
  window.GestureLock.GestureLockTimeoutError = GestureLockTimeoutError;
}
