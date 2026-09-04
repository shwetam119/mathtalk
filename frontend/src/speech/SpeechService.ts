/**
 * Speech-to-text service (Web Speech API).
 *
 * Responsibilities: listen(), stop_listening(), cancel_listening(),
 * handle_transcript(), handle_recognition_error(). It emits interim results so
 * the app can implement barge-in (stop current speech as soon as the student
 * starts talking), and it guards against duplicate/overlapping turns at the
 * app level.
 */

export type SpeechStatus =
  | "idle"
  | "listening"
  | "unsupported"
  | "no-speech"
  | "mic-error"
  | "network-error"
  | "restarting";

export interface SpeechCallbacks {
  onFinal: (text: string) => void;
  onInterim: (text: string) => void;
  onStatus: (status: SpeechStatus, detail?: string) => void;
}

export class SpeechService {
  private recognition: any = null;
  private supported = false;
  private stopped = true;
  private restartTimer: number | null = null;
  private callbacks: SpeechCallbacks;
  private lastFinal = "";
  private lastFinalAt = 0;

  constructor(callbacks: SpeechCallbacks) {
    this.callbacks = callbacks;
    const w = window as any;
    const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
    this.supported = Boolean(Ctor);
    if (this.supported) {
      this.recognition = new Ctor();
      this.recognition.lang = "en-US";
      this.recognition.interimResults = true;
      this.recognition.continuous = false;
      this.recognition.maxAlternatives = 1;

      this.recognition.onresult = (event: any) => {
        let interim = "";
        let final = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const r = event.results[i];
          const text = r[0].transcript.trim();
          if (r.isFinal) final += " " + text;
          else interim += " " + text;
        }
        const interimText = interim.trim();
        const finalText = final.trim();
        if (interimText) this.callbacks.onInterim(interimText);
        if (finalText) this.handleFinal(finalText);
      };

      this.recognition.onerror = (event: any) => {
        const err = event?.error || "unknown";
        switch (err) {
          case "no-speech":
            this.callbacks.onStatus("no-speech");
            break;
          case "not-allowed":
          case "service-not-allowed":
          case "audio-capture":
            this.callbacks.onStatus("mic-error", err);
            this.stopped = true;
            break;
          case "network":
            this.callbacks.onStatus("network-error");
            break;
          default:
            this.callbacks.onStatus("restarting", err);
        }
      };

      this.recognition.onend = () => {
        if (!this.stopped) this.scheduleRestart();
      };
    }
  }

  get isSupported(): boolean {
    return this.supported;
  }

  private handleFinal(text: string) {
    // duplicate-turn guard: identical transcripts within 3.5s are ignored
    const now = Date.now();
    if (text === this.lastFinal && now - this.lastFinalAt < 3500) return;
    this.lastFinal = text;
    this.lastFinalAt = now;
    this.callbacks.onFinal(text);
  }

  private scheduleRestart() {
    if (this.stopped) return;
    if (this.restartTimer) window.clearTimeout(this.restartTimer);
    this.restartTimer = window.setTimeout(() => {
      if (!this.stopped) {
        try {
          this.callbacks.onStatus("restarting");
          this.recognition.start();
        } catch {
          /* already started */
        }
      }
    }, 350);
  }

  /** Start (or resume) listening. */
  listen() {
    if (!this.supported) {
      this.callbacks.onStatus("unsupported");
      return;
    }
    this.stopped = false;
    try {
      this.recognition.start();
      this.callbacks.onStatus("listening");
    } catch {
      // already running — fine
    }
  }

  /** Pause listening (recognition stops; no restart). */
  stop_listening() {
    this.stopped = true;
    if (this.restartTimer) {
      window.clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    try {
      this.recognition?.stop();
    } catch {
      /* ignore */
    }
  }

  /** Hard cancel (used on STOP command). */
  cancel_listening() {
    this.stop_listening();
    this.callbacks.onStatus("idle");
  }
}
