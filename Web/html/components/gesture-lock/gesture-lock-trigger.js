import {
  openGestureLock,
  GestureLockCancelledError,
  GestureLockTimeoutError,
} from './index.js';

const DEFAULT_SELECTOR = '[data-gesture-lock-trigger]';
const STATUS_VARIANTS = ['info', 'success', 'error', 'warn'];

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const buildOptions = (trigger) => {
  const options = {};
  const endpoint = trigger.dataset.gestureEndpoint;
  if (endpoint) {
    options.endpoint = endpoint;
  }

  const timeout = toNumber(trigger.dataset.gestureTimeout, 0);
  if (timeout > 0) {
    options.timeout = timeout;
  }

  return options;
};

const mapErrorToStatus = (error) => {
  if (error instanceof GestureLockCancelledError) {
    return { message: '已取消当前验证', variant: 'info' };
  }
  if (error instanceof GestureLockTimeoutError) {
    return { message: '验证超时，请重试。', variant: 'error' };
  }
  return {
    message: (error && error.message) || '验证失败，请稍后重试。',
    variant: 'error',
  };
};

const dispatchSuccess = (trigger, detail) => {
  const eventName = trigger.dataset.gestureSuccessEvent || 'gesture-lock-key';
  const targetSelector = trigger.dataset.gestureEventTarget;
  const target = targetSelector ? document.querySelector(targetSelector) : window;
  const eventTarget = target || window;
  eventTarget.dispatchEvent(
    new CustomEvent(eventName, {
      detail,
    })
  );

  const callbackName = trigger.dataset.gestureSuccessFn;
  if (callbackName && typeof window[callbackName] === 'function') {
    try {
      window[callbackName](detail, trigger);
    } catch (error) {
      console.error('[GestureLock] success 回调执行失败:', error);
    }
  }
};

const attachTrigger = (trigger) => {
  if (!trigger || trigger.dataset.gestureAttached === 'true') {
    return;
  }
  trigger.dataset.gestureAttached = 'true';

  const statusSelector = trigger.dataset.gestureStatusTarget;
  const statusEl = statusSelector ? document.querySelector(statusSelector) : null;
  const useToast = trigger.dataset.gestureUseToast === 'true' && typeof window.showToast === 'function';
  const statusDuration = Math.max(toNumber(trigger.dataset.gestureStatusDuration, 3200), 0);
  let statusTimer;

  const clearStatus = () => {
    if (useToast || !statusEl) {
      return;
    }
    statusEl.classList.remove('show');
    STATUS_VARIANTS.forEach((variant) => statusEl.classList.remove(variant));
    statusEl.textContent = '';
  };

  const setStatus = (message, variant = 'info') => {
    if (useToast) {
      const toastVariantMap = {
        success: 'success',
        error: 'error',
        warn: 'warning',
        info: 'info',
      };
      const toastType = toastVariantMap[variant] || 'info';
      window.showToast(message, toastType);
      return;
    }

    if (!statusEl) {
      console.info('[GestureLock]', message);
      return;
    }
    clearTimeout(statusTimer);
    statusEl.textContent = message;
    statusEl.classList.add('show');
    STATUS_VARIANTS.forEach((item) => statusEl.classList.remove(item));
    statusEl.classList.add(variant);
    statusTimer = setTimeout(() => {
      clearStatus();
    }, statusDuration);
  };

  trigger.addEventListener('click', async () => {
    if (trigger.disabled) {
      return;
    }

    trigger.disabled = true;
    trigger.setAttribute('aria-expanded', 'true');
    trigger.setAttribute('aria-busy', 'true');
    setStatus('请在面板中完成手势验证...', 'info');

    try {
      const detail = await openGestureLock(buildOptions(trigger));
      const keyText = detail && detail.key ? `验证成功：${detail.key}` : '验证成功';
      setStatus(keyText, 'success');
      dispatchSuccess(trigger, detail);
    } catch (error) {
      const mapped = mapErrorToStatus(error);
      setStatus(mapped.message, mapped.variant);
    } finally {
      trigger.disabled = false;
      trigger.setAttribute('aria-expanded', 'false');
      trigger.removeAttribute('aria-busy');
    }
  });
};

const initGestureLockTriggers = (selector = DEFAULT_SELECTOR) => {
  const triggers = document.querySelectorAll(selector);
  if (!triggers.length) {
    return;
  }
  triggers.forEach((trigger) => attachTrigger(trigger));
};

const ready = () => initGestureLockTriggers();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ready, { once: true });
} else {
  ready();
}

export { attachTrigger, initGestureLockTriggers };
