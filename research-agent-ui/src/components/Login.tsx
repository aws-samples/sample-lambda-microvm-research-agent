import { useState } from 'react';
import { signIn, signUp, confirmSignUp, resetPassword, confirmResetPassword } from 'aws-amplify/auth';

interface LoginProps {
  onSuccess: (email: string) => void;
}

export function Login({ onSuccess }: LoginProps) {
  const [mode, setMode] = useState<'signin' | 'signup' | 'confirm' | 'forgotPassword' | 'resetCode'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await signIn({ username: email, password });
      if (result.isSignedIn) {
        onSuccess(email);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Sign in failed');
    } finally {
      setLoading(false);
    }
  };

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await signUp({ username: email, password, options: { userAttributes: { email } } });
      setMode('confirm');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Sign up failed');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await confirmSignUp({ username: email, confirmationCode: code });
      const result = await signIn({ username: email, password });
      if (result.isSignedIn) {
        onSuccess(email);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Confirmation failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <h1>Research Agent</h1>
        <p className="subtitle">AI-powered research, powered by Lambda MicroVMs</p>

        {error && <div className="error-msg">{error}</div>}

        {mode === 'signin' && (
          <form onSubmit={handleSignIn}>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              aria-label="Email"
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              aria-label="Password"
            />
            <button type="submit" disabled={loading}>
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
            <p className="switch-mode">
              <button type="button" onClick={() => setMode('forgotPassword')}>
                Forgot password?
              </button>
            </p>
            <p className="switch-mode">
              No account?{' '}
              <button type="button" onClick={() => setMode('signup')}>
                Sign Up
              </button>
            </p>
          </form>
        )}

        {mode === 'signup' && (
          <form onSubmit={handleSignUp}>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              aria-label="Email"
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              aria-label="Password"
            />
            <button type="submit" disabled={loading}>
              {loading ? 'Creating account...' : 'Sign Up'}
            </button>
            <p className="switch-mode">
              Have an account?{' '}
              <button type="button" onClick={() => setMode('signin')}>
                Sign In
              </button>
            </p>
          </form>
        )}

        {mode === 'forgotPassword' && (
          <form onSubmit={async (e) => {
            e.preventDefault();
            setError('');
            setLoading(true);
            try {
              await resetPassword({ username: email });
              setMode('resetCode');
            } catch (err: unknown) {
              setError(err instanceof Error ? err.message : 'Failed to send reset code');
            } finally {
              setLoading(false);
            }
          }}>
            <p className="confirm-text">Enter your email to receive a reset code.</p>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              aria-label="Email"
            />
            <button type="submit" disabled={loading}>
              {loading ? 'Sending...' : 'Send Reset Code'}
            </button>
            <p className="switch-mode">
              <button type="button" onClick={() => setMode('signin')}>
                Back to Sign In
              </button>
            </p>
          </form>
        )}

        {mode === 'resetCode' && (
          <form onSubmit={async (e) => {
            e.preventDefault();
            setError('');
            setLoading(true);
            try {
              await confirmResetPassword({ username: email, confirmationCode: code, newPassword });
              const result = await signIn({ username: email, password: newPassword });
              if (result.isSignedIn) {
                onSuccess(email);
              }
            } catch (err: unknown) {
              setError(err instanceof Error ? err.message : 'Reset failed');
            } finally {
              setLoading(false);
            }
          }}>
            <p className="confirm-text">Enter the code sent to your email and a new password.</p>
            <input
              type="text"
              placeholder="Verification code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              aria-label="Verification code"
            />
            <input
              type="password"
              placeholder="New password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              aria-label="New password"
            />
            <button type="submit" disabled={loading}>
              {loading ? 'Resetting...' : 'Reset Password'}
            </button>
            <p className="switch-mode">
              <button type="button" onClick={() => setMode('signin')}>
                Back to Sign In
              </button>
            </p>
          </form>
        )}

        {mode === 'confirm' && (
          <form onSubmit={handleConfirm}>
            <p className="confirm-text">Check your email for a verification code.</p>
            <input
              type="text"
              placeholder="Verification code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              aria-label="Verification code"
            />
            <button type="submit" disabled={loading}>
              {loading ? 'Verifying...' : 'Confirm'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
