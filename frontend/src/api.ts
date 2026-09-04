import type { ServiceConfig, TimelineResponse, TurnResponse, VoiceSpeakResponse } from "./types";

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return (await res.json()) as T;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const api = {
  startSession: (studentId: string, forceNew = false) =>
    postJSON<TurnResponse>("/api/session/start", { student_id: studentId, force_new: forceNew }),

  sendTurn: (studentId: string, transcript: string, source: "speech" | "text", confidence = 1.0) =>
    postJSON<TurnResponse>("/api/session/turn", { student_id: studentId, transcript, source, confidence }),

  sendCommand: (studentId: string, intent: string, option?: string) =>
    postJSON<TurnResponse>("/api/session/command", { student_id: studentId, intent, option }),

  setVoiceStatus: (studentId: string, status: string) =>
    postJSON<{ ok: boolean }>("/api/session/voice-status", { student_id: studentId, status }),

  speak: (text: string) => postJSON<VoiceSpeakResponse>("/api/voice/speak", { text }),

  getConfig: () => getJSON<ServiceConfig>("/api/config"),

  getMemories: (studentId: string) =>
    getJSON<{ student_id: string; memories: unknown[] }>(`/api/memory/${encodeURIComponent(studentId)}`),

  getMisconceptionTimeline: (studentId: string, misconceptionType: string) =>
    getJSON<TimelineResponse>(
      `/api/students/${encodeURIComponent(studentId)}/misconceptions/${encodeURIComponent(misconceptionType)}/timeline`
    ),

  deleteMemories: (studentId: string) =>
    fetch(`/api/memory/${encodeURIComponent(studentId)}`, { method: "DELETE" }),

  resetDemo: (studentId: string) =>
    postJSON<{ reset: boolean; student_id: string }>("/api/demo/reset", { student_id: studentId }),
};
