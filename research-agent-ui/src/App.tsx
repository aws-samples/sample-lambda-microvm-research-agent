import { useState, useEffect } from 'react';
import { getCurrentUser, signOut } from 'aws-amplify/auth';
import { Login } from './components/Login';
import { Chat } from './components/Chat';

export default function App() {
  const [user, setUser] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCurrentUser()
      .then((u) => setUser(u.username))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const handleLogout = async () => {
    await signOut();
    setUser(null);
  };

  if (loading) {
    return <div className="loading">Loading...</div>;
  }

  if (!user) {
    return <Login onSuccess={(username) => setUser(username)} />;
  }

  return <Chat username={user} onLogout={handleLogout} />;
}
