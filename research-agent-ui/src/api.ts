import { fetchAuthSession } from 'aws-amplify/auth';
import { API_ENDPOINT } from './config';

const BASE_URL = API_ENDPOINT.replace(/\/+$/, '');

async function getAuthToken(): Promise<string> {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  if (!token) throw new Error('Not authenticated');
  return token;
}

export interface ResearchResponse {
  success: boolean;
  sessionId: string;
  task: string;
  report: string;
  messagesInSession: number;
  error?: string;
}

export interface Session {
  session_id: string;
  findings_count: number;
  created_at: string;
  messages: number;
}

interface TaskStatus {
  taskId: string;
  status: 'PENDING' | 'COMPLETED' | 'FAILED';
  task: string;
  sessionId: string;
  report: string;
  error: string;
}

async function submitTask(task: string, sessionId?: string): Promise<string> {
  const token = await getAuthToken();
  const res = await fetch(`${BASE_URL}/research`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: token,
    },
    body: JSON.stringify({ task, sessionId }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || 'Submit failed');
  }
  const data = await res.json();
  return data.taskId;
}

async function pollTask(taskId: string): Promise<TaskStatus> {
  const token = await getAuthToken();
  const res = await fetch(`${BASE_URL}/tasks/${taskId}`, {
    headers: { Authorization: token },
  });
  if (!res.ok) throw new Error('Poll failed');
  return res.json();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function submitResearch(task: string, sessionId?: string): Promise<ResearchResponse> {
  const taskId = await submitTask(task, sessionId);

  // Poll until complete (max 2 minutes)
  const maxAttempts = 24;
  let consecutiveErrors = 0;

  for (let i = 0; i < maxAttempts; i++) {
    await sleep(5000);

    let status: TaskStatus;
    try {
      status = await pollTask(taskId);
      consecutiveErrors = 0;
    } catch {
      consecutiveErrors++;
      if (consecutiveErrors >= 3) {
        throw new Error('Failed to check task status after multiple retries');
      }
      continue;
    }

    if (status.status === 'COMPLETED') {
      return {
        success: true,
        sessionId: status.sessionId,
        task: status.task,
        report: status.report,
        messagesInSession: 0,
      };
    }

    if (status.status === 'FAILED') {
      throw new Error(status.error || 'Research failed');
    }
  }

  throw new Error('Research is taking too long. Please try again with a simpler question.');
}

export async function listSessions(): Promise<Session[]> {
  return [];
}
