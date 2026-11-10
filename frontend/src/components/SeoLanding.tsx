import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { getSeoRoute, type SeoRoute, type FaqItem } from '@/config/seoRoutes';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SeoLandingProps {
  pathname: string;
  children: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Head-tag helpers (create-or-update meta / link in document.head)
// ---------------------------------------------------------------------------

function upsertMeta(attr: 'name' | 'property', key: string, content: string): HTMLMetaElement {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
  return el;
}

function upsertLink(rel: string, href: string): HTMLLinkElement {
  let el = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', rel);
    document.head.appendChild(el);
  }
  el.setAttribute('href', href);
  return el;
}

// ---------------------------------------------------------------------------
// JSON-LD builders
// ---------------------------------------------------------------------------

function buildSoftwareAppLD(route: SeoRoute) {
  return {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: 'Snacky Studio',
    applicationCategory: 'MultimediaApplication',
    operatingSystem: 'Web, Windows, macOS, Linux, Docker',
    description: route.metaDescription,
    url: window.location.origin + route.canonical,
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    featureList: [
      'MP4 video download with resolution selection',
      'MP3 audio extraction with bitrate control (128–320 kbps)',
      'Instagram carousel to ZIP archive',
      'TikTok photo slideshow to MP4 with original music',
      'Lossless PNG photo conversion',
      'Batch link queue (up to 50)',
      'Self-hosted Docker deployment',
      'Tauri desktop app for Windows, macOS, Linux',
    ],
  };
}

function buildFaqPageLD(faqs: FaqItem[]) {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqs.map((faq) => ({
      '@type': 'Question',
      name: faq.question,
      acceptedAnswer: { '@type': 'Answer', text: faq.answer },
    })),
  };
}

// ---------------------------------------------------------------------------
// FAQ Accordion Item
// ---------------------------------------------------------------------------

function FaqAccordionItem({ faq }: { faq: FaqItem }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-b border-border/40 last:border-b-0">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-4 py-4 text-left text-sm font-medium text-foreground transition-colors hover:text-primary"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span>{faq.question}</span>
        <ChevronDown
          size={16}
          className={`shrink-0 text-muted-foreground transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>
      <div
        className={`overflow-hidden transition-all duration-200 ${open ? 'max-h-96 pb-4' : 'max-h-0'}`}
        role="region"
      >
        <p className="text-sm leading-relaxed text-muted-foreground">{faq.answer}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feature Card
// ---------------------------------------------------------------------------

function FeatureCard({ feature }: { feature: { icon: string; title: string; description: string } }) {
  return (
    <div className="rounded-xl border border-border/40 bg-card/50 p-5 backdrop-blur-sm">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-primary">{feature.icon}</span>
        <h3 className="text-sm font-semibold text-foreground">{feature.title}</h3>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">{feature.description}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SeoLanding wrapper component
// ---------------------------------------------------------------------------

export function SeoLanding({ pathname, children }: SeoLandingProps) {
  const injected = useRef<HTMLElement[]>([]);
  const route = getSeoRoute(pathname);
  const origin = window.location.origin;

  // ---- Head tag management ------------------------------------------------
  useEffect(() => {
    const els: HTMLElement[] = [];

    // Title
    document.title = route.title;

    // Standard meta
    els.push(upsertMeta('name', 'description', route.metaDescription));
    els.push(upsertMeta('name', 'keywords', route.keywords));
    els.push(upsertLink('canonical', origin + route.canonical));

    // Open Graph
    els.push(upsertMeta('property', 'og:type', 'website'));
    els.push(upsertMeta('property', 'og:site_name', 'Snacky Studio'));
    els.push(upsertMeta('property', 'og:title', route.title));
    els.push(upsertMeta('property', 'og:description', route.metaDescription));
    els.push(upsertMeta('property', 'og:url', origin + route.canonical));
    els.push(upsertMeta('property', 'og:image', origin + '/static/og-image.png'));

    // Twitter / X card
    els.push(upsertMeta('name', 'twitter:card', 'summary_large_image'));
    els.push(upsertMeta('name', 'twitter:title', route.title));
    els.push(upsertMeta('name', 'twitter:description', route.metaDescription));
    els.push(upsertMeta('name', 'twitter:image', origin + '/static/og-image.png'));

    // JSON-LD structured data
    const ldApp = document.createElement('script');
    ldApp.type = 'application/ld+json';
    ldApp.textContent = JSON.stringify(buildSoftwareAppLD(route));
    document.head.appendChild(ldApp);
    els.push(ldApp);

    const ldFaq = document.createElement('script');
    ldFaq.type = 'application/ld+json';
    ldFaq.textContent = JSON.stringify(buildFaqPageLD(route.faqs));
    document.head.appendChild(ldFaq);
    els.push(ldFaq);

    injected.current = els;

    return () => {
      // Remove only the JSON-LD scripts on cleanup (meta tags are reused via upsert)
      for (const el of injected.current) {
        if (el.tagName === 'SCRIPT') {
          el.remove();
        }
      }
    };
  }, [route, origin]);

  // ---- Render -------------------------------------------------------------
  return (
    <>
      {/* The functional downloader UI always renders first (above the fold) */}
      {children}

      {/* Below-the-fold SEO content */}
      <section className="seo-content mx-auto max-w-3xl px-4 pb-16 pt-12">
        {/* Route-specific H1 (visually styled, duplicates the server-injected h1 for SPA nav) */}
        <h1 className="mb-3 text-center text-2xl font-bold tracking-tight text-foreground md:text-3xl">
          {route.h1}
        </h1>
        <p className="mx-auto mb-10 max-w-2xl text-center text-sm leading-relaxed text-muted-foreground">
          {route.subtitle}
        </p>

        {/* Feature highlight cards */}
        <div className="mb-12 grid gap-4 sm:grid-cols-2">
          {route.features.map((f) => (
            <FeatureCard key={f.title} feature={f} />
          ))}
        </div>

        {/* FAQ accordion */}
        <div className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-foreground">Frequently Asked Questions</h2>
          <div className="rounded-xl border border-border/40 bg-card/30 px-5">
            {route.faqs.map((faq) => (
              <FaqAccordionItem key={faq.question} faq={faq} />
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

