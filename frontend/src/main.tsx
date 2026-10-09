import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import { ReferenceProvider } from './api/ReferenceContext';
import App from './App';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ReferenceProvider>
          <App />
        </ReferenceProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
