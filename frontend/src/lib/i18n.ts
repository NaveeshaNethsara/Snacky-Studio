import { createContext, useContext, useState, useEffect, ReactNode, createElement } from 'react';

export type Language = 'en' | 'es';

export interface Translations {
  [key: string]: string;
}

export const translations: Record<Language, Translations> = {
  en: {
    // Header & Workspace
    brandName: 'Snacky Studio',
    privateCloud: 'Private cloud',
    localWorkspace: 'Local workspace',
    unlimitedBadge: '👑 Unlimited',
    admin: 'Admin',
    openFolder: 'Open folder',
    settings: 'Settings',
    signOut: 'Sign out',
    signIn: 'Sign in',
    skipToContent: 'Skip to downloader',

    // Hero
    eyebrow: 'YOUR MEDIA, YOUR WAY',
    heroTitle1: 'Keep the moments',
    heroTitle2: 'you love.',
    heroDesc: 'Videos, audio, and photo posts. One link. Yours to keep.',

    // Tabs
    singleMode: 'Single Link',
    batchMode: 'Batch Links',

    // Single Form
    singleInputLabel: 'Video or photo-post link',
    singlePlaceholder: 'Paste a video or photo-post link…',
    continueBtn: 'Continue',
    checkingBtn: 'Checking…',
    getPhotoBtn: 'Get photo',
    pasteBtn: 'Paste',
    clearBtn: 'Clear link',
    downloadSuccessNotice: 'Your download is on its way. You can paste another link now.',

    // Batch Form
    batchInputLabel: 'Paste multiple links (one per line, up to 50)',
    batchPlaceholder: 'https://youtube.com/watch?v=...\nhttps://instagram.com/p/...\nhttps://tiktok.com/@user/video/...',
    batchCount: '{count} link(s) detected',
    batchStartBtn: 'Start Batch Download',
    batchProcessingBtn: 'Submitting Batch…',
    batchSuccessNotice: 'Batch started with {count} downloads.',
    batchProgressHeading: 'Batch in Progress',
    batchSummary: '{completed} of {total} completed ({failed} failed)',
    formatSelect: 'Format',
    qualitySelect: 'Quality',

    // Task List
    activeDownloads: 'Downloads',
    queued: 'Queued',
    fetching_info: 'Checking link…',
    downloading: 'Downloading',
    processing: 'Processing',
    finishing: 'Finishing…',
    cancelling: 'Cancelling…',
    cancelled: 'Cancelled',
    interrupted: 'Interrupted',
    completed: 'Completed',
    error: 'Failed',
    retryBtn: 'Retry',
    cancelBtn: 'Cancel',
    saveBtn: 'Save',
    dismissBtn: 'Dismiss',
    anotherDownload: 'Download another',

    // Library
    libraryTitle: 'Recent downloads',
    viewAll: 'View all ({count})',
    showLess: 'Show less',
    refreshDownloads: 'Refresh downloads',
    searchFiles: 'Search files by title or format…',
    filterAll: 'All',
    filterVideo: 'Videos',
    filterAudio: 'Audio',
    filterPhotos: 'Photos',
    sortLabel: 'Sort',
    sortNewest: 'Newest first',
    sortOldest: 'Oldest first',
    sortLargest: 'Largest first',
    sortSmallest: 'Smallest first',
    sortNameAsc: 'Name (A-Z)',
    sortNameDesc: 'Name (Z-A)',
    emptyLibrary: 'Your saved media will appear here.',
    noMatchingFiles: 'No files match your search.',
    libraryStats: '{count} files · {size} GB saved',
    deleteFile: 'Delete',

    // Preferences Modal
    prefTitle: 'Preferences & Settings',
    prefDesc: 'Customize your default download quality, appearance, and language.',
    themeLabel: 'Appearance Theme',
    themeSystem: 'System default',
    themeDark: 'Dark mode',
    themeLight: 'Light mode',
    langLabel: 'Language / Idioma',
    defaultFormatLabel: 'Default Format',
    defaultQualityLabel: 'Default Video Resolution',
    defaultBitrateLabel: 'Default Audio Bitrate',
    autoSaveLabel: 'Auto-save downloads to browser',
    savePreferencesBtn: 'Save Preferences',
    prefSavedNotice: 'Preferences saved successfully.',

    // Footer & Dialogs
    howItWorks: 'How it works',
    howItWorksTitle: 'A link is all you need.',
    howItWorksDesc: 'Paste a public media link, choose your format, and download. We prepare the file before handing it to your browser. You can start another download while it works.',
    howItWorksNote: 'Photo collections save as ZIP. TikTok slideshows use the available original music. Keep the local server running until your file finishes saving.',
    gotIt: 'Got it',
    deleteModalTitle: 'Delete this file?',
    deleteModalDesc: 'This removes {filename} from your media library.',
    keepFile: 'Keep file',
    confirmDelete: 'Delete file',
    deletingBtn: 'Deleting…',
    cloudFooter: 'Your private media workspace.',
    localFooter: 'Made for your media. Saved on your device.',
  },
  es: {
    // Header & Workspace
    brandName: 'Snacky Studio',
    privateCloud: 'Nube privada',
    localWorkspace: 'Espacio local',
    unlimitedBadge: '👑 Ilimitado',
    admin: 'Admin',
    openFolder: 'Abrir carpeta',
    settings: 'Ajustes',
    signOut: 'Cerrar sesión',
    signIn: 'Iniciar sesión',
    skipToContent: 'Saltar al descargador',

    // Hero
    eyebrow: 'TUS MEDIOS, A TU MANERA',
    heroTitle1: 'Guarda los momentos',
    heroTitle2: 'que amas.',
    heroDesc: 'Videos, audios y fotos. Un enlace. Tuyo para siempre.',

    // Tabs
    singleMode: 'Enlace único',
    batchMode: 'Descarga masiva',

    // Single Form
    singleInputLabel: 'Enlace de video o publicación de fotos',
    singlePlaceholder: 'Pega un enlace de video o publicación…',
    continueBtn: 'Continuar',
    checkingBtn: 'Analizando…',
    getPhotoBtn: 'Obtener foto',
    pasteBtn: 'Pegar',
    clearBtn: 'Borrar enlace',
    downloadSuccessNotice: 'Tu descarga ha comenzado. Puedes pegar otro enlace ahora.',

    // Batch Form
    batchInputLabel: 'Pega múltiples enlaces (uno por línea, hasta 50)',
    batchPlaceholder: 'https://youtube.com/watch?v=...\nhttps://instagram.com/p/...\nhttps://tiktok.com/@usuario/video/...',
    batchCount: '{count} enlace(s) detectado(s)',
    batchStartBtn: 'Iniciar descarga masiva',
    batchProcessingBtn: 'Enviando lote…',
    batchSuccessNotice: 'Descarga masiva iniciada con {count} enlaces.',
    batchProgressHeading: 'Lote en progreso',
    batchSummary: '{completed} de {total} completados ({failed} fallidos)',
    formatSelect: 'Formato',
    qualitySelect: 'Calidad',

    // Task List
    activeDownloads: 'Descargas',
    queued: 'En cola',
    fetching_info: 'Comprobando enlace…',
    downloading: 'Descargando',
    processing: 'Procesando',
    finishing: 'Finalizando…',
    cancelling: 'Cancelando…',
    cancelled: 'Cancelado',
    interrupted: 'Interrumpido',
    completed: 'Completado',
    error: 'Error',
    retryBtn: 'Reintentar',
    cancelBtn: 'Cancelar',
    saveBtn: 'Guardar',
    dismissBtn: 'Descartar',
    anotherDownload: 'Descargar otro',

    // Library
    libraryTitle: 'Descargas recientes',
    viewAll: 'Ver todos ({count})',
    showLess: 'Mostrar menos',
    refreshDownloads: 'Actualizar descargas',
    searchFiles: 'Buscar archivos por título o formato…',
    filterAll: 'Todos',
    filterVideo: 'Videos',
    filterAudio: 'Audio',
    filterPhotos: 'Fotos',
    sortLabel: 'Ordenar',
    sortNewest: 'Más recientes primero',
    sortOldest: 'Más antiguos primero',
    sortLargest: 'Más grandes primero',
    sortSmallest: 'Más pequeños primero',
    sortNameAsc: 'Nombre (A-Z)',
    sortNameDesc: 'Nombre (Z-A)',
    emptyLibrary: 'Tus archivos guardados aparecerán aquí.',
    noMatchingFiles: 'No se encontraron archivos que coincidan.',
    libraryStats: '{count} archivos · {size} GB guardados',
    deleteFile: 'Eliminar',

    // Preferences Modal
    prefTitle: 'Preferencias y Ajustes',
    prefDesc: 'Personaliza la calidad de descarga predeterminada, apariencia e idioma.',
    themeLabel: 'Tema de apariencia',
    themeSystem: 'Predeterminado del sistema',
    themeDark: 'Modo oscuro',
    themeLight: 'Modo claro',
    langLabel: 'Idioma / Language',
    defaultFormatLabel: 'Formato predeterminado',
    defaultQualityLabel: 'Resolución de video predeterminada',
    defaultBitrateLabel: 'Bitrate de audio predeterminado',
    autoSaveLabel: 'Guardar descargas automáticamente en el navegador',
    savePreferencesBtn: 'Guardar preferencias',
    prefSavedNotice: 'Preferencias guardadas con éxito.',

    // Footer & Dialogs
    howItWorks: 'Cómo funciona',
    howItWorksTitle: 'Un enlace es todo lo que necesitas.',
    howItWorksDesc: 'Pega un enlace público, elige tu formato y descarga. Preparamos el archivo antes de entregarlo a tu navegador.',
    howItWorksNote: 'Las colecciones de fotos se guardan en ZIP. Los videos de TikTok usan su música original.',
    gotIt: 'Entendido',
    deleteModalTitle: '¿Eliminar este archivo?',
    deleteModalDesc: 'Esto eliminará {filename} de tu biblioteca de medios.',
    keepFile: 'Conservar archivo',
    confirmDelete: 'Eliminar archivo',
    deletingBtn: 'Eliminando…',
    cloudFooter: 'Tu espacio privado de medios.',
    localFooter: 'Hecho para tus medios. Guardado en tu dispositivo.',
  },
};

interface I18nContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextType>({
  language: 'en',
  setLanguage: () => {},
  t: (key) => key,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() => {
    try {
      const saved = localStorage.getItem('snacky_language');
      if (saved === 'es' || saved === 'en') return saved;
      if (navigator.language.startsWith('es')) return 'es';
    } catch {
      // Fallback to English
    }
    return 'en';
  });

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    try {
      localStorage.setItem('snacky_language', lang);
      document.documentElement.lang = lang;
    } catch {
      // Ignore
    }
  };

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const t = (key: string, params?: Record<string, string | number>): string => {
    const dict = translations[language] || translations.en;
    let template = dict[key] || translations.en[key] || key;
    if (params) {
      Object.entries(params).forEach(([paramKey, val]) => {
        template = template.replace(new RegExp(`\\{${paramKey}\\}`, 'g'), String(val));
      });
    }
    return template;
  };

  return createElement(I18nContext.Provider, { value: { language, setLanguage, t } }, children);
}

export function useTranslation() {
  return useContext(I18nContext);
}

