// Importazione delle dipendenze necessarie
import React, { useState, useEffect } from 'react';
import { SunIcon, MoonIcon } from 'lucide-react';
import { useApp } from '../../contexts/AppContext';

// Componente SigmaNetwork
const SigmaNetwork = () => {
  // Il tema si legge dal contesto, come negli altri moduli: riceverlo come
  // prop obbligava ogni chiamante a conoscerlo, e il Workspace non lo ha.
  const { theme } = useApp();
  const isLight = theme === 'light';

  const [identity, setIdentity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Fetch identity from the API
    fetch('/api/sigma_network/identity')
      .then(response => {
        if (!response.ok) {
          throw new Error('Network response was not ok ' + response.statusText);
        }
        return response.json();
      })
      .then(data => {
        setIdentity(data);
      })
      .catch(err => {
        setError(err.message);
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (error) {
    return <div>Error: {error}</div>;
  }

  if (!identity) {
    return <div>No identity data available</div>;
  }

  return (
    <div style={{ color: isLight ? '#000' : '#fff', backgroundColor: isLight ? '#fff' : '#000', padding: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <h1>Sigma Network</h1>
      <div style={{ marginBottom: '20px' }}>
        <span style={{ marginRight: '10px' }}>Peer ID: {identity.peer_id}</span>
        <span>Name: {identity.name}</span>
      </div>
      <button style={{ padding: '10px 20px', margin: '5px', backgroundColor: isLight ? '#ddd' : '#333', color: isLight ? '#000' : '#fff', border: 'none', borderRadius: '5px' }}>Peer List</button>
      <button style={{ padding: '10px 20px', margin: '5px', backgroundColor: isLight ? '#ddd' : '#333', color: isLight ? '#000' : '#fff', border: 'none', borderRadius: '5px' }}>Settings</button>
    </div>
  );
};

export default SigmaNetwork;
