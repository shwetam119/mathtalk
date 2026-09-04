/**
 * Speech-output player.
 *
 * Primary path: Rime audio synthesized by the backend (server-side secrets
 * never reach the browser). Fallback path (only when Rime is not configured):
 * browser speech synthesis — clearly surfaced in the UI as a fallback.
 *
 * Also implements barge-in: stopSpeaking() stops any currently playing audio
 * immediately so the student's new utterance can be captured.
 */

let audioEl: HTMLAudioElement | null = null;
let activeObjectUrl: string | null = null;

function ensureAudioElement(): HTMLAudioElement {
  if (!audioEl) {
    audioEl = new Audio();
    audioEl.preload = "auto";
  }
  return audioEl;
}

export function playRimeAudio(base64: string, mime: string): Promise<void> {
  const el = ensureAudioElement();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.clearTimeout(timer);
      resolve();
    };
    const timer = window.setTimeout(finish, 30000); // never hang the loop
    try {
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
      const blob = new Blob([bytes], { type: mime || "audio/wav" });
      if (activeObjectUrl) URL.revokeObjectURL(activeObjectUrl);
      activeObjectUrl = URL.createObjectURL(blob);
      el.src = activeObjectUrl;
      el.onended = finish;
      el.onerror = finish;
      el.play().catch(finish);
    } catch {
      finish();
    }
  });
}

export function speakWithBrowser(text: string): Promise<void> {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    if (!synth) return resolve();
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.clearTimeout(timer);
      resolve();
    };
    const timer = window.setTimeout(finish, 20000); // never hang the loop
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.0;
    u.pitch = 1.0;
    u.onend = finish;
    u.onerror = finish;
    synth.speak(u);
  });
}

/** Stop all speech immediately (barge-in / STOP command). */
export function stopSpeaking() {
  if (audioEl) {
    audioEl.pause();
    audioEl.onended = null;
  }
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  if (activeObjectUrl) {
    URL.revokeObjectURL(activeObjectUrl);
    activeObjectUrl = null;
  }
}
