import { createRoot } from 'react-dom/client';
import { useState, useEffect } from 'react';
import App from './App';
import { SeoLanding } from './components/SeoLanding';
import { I18nProvider } from './lib/i18n';
import { seoRoutes } from './config/seoRoutes';
import './index.css';

// Initialize theme from preferences or default dark
try {
  const savedTheme = localStorage.getItem('snacky_theme');
  if (savedTheme === 'light') {
    document.documentElement.classList.remove('dark');
    document.documentElement.classList.add('light');
  } else {
    document.documentElement.classList.add('dark');
  }
} catch {
  document.documentElement.classList.add('dark');
}

const seoPathSet = new Set(seoRoutes.map((r) => r.path));

function Root() {
  const [pathname, setPathname] = useState(window.location.pathname);

  useEffect(() => {
    const onPop = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const isSeoRoute = seoPathSet.has(pathname);

  return (
    <I18nProvider>
      {isSeoRoute ? (
        <SeoLanding pathname={pathname}>
          <App />
        </SeoLanding>
      ) : (
        <App />
      )}
    </I18nProvider>
  );
}

createRoot(document.getElementById('root')!).render(<Root />);
