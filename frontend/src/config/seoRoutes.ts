/** Centralised SEO configuration for every programmatic landing route. */

export interface FaqItem {
  question: string;
  answer: string;
}

export interface FeatureBullet {
  icon: string; // lucide-react icon name
  title: string;
  description: string;
}

export interface SeoRoute {
  path: string;
  title: string;
  metaDescription: string;
  canonical: string;
  h1: string;
  subtitle: string;
  keywords: string;
  features: FeatureBullet[];
  faqs: FaqItem[];
}

// ---------------------------------------------------------------------------
// Route definitions
// ---------------------------------------------------------------------------

export const seoRoutes: SeoRoute[] = [
  // -----------------------------------------------------------------------
  // 1. Home — broad multi-platform
  // -----------------------------------------------------------------------
  {
    path: '/',
    title: 'Snacky Studio — Free Social Media Video, Audio & Photo Downloader',
    metaDescription:
      'Download videos, audio, and photos from YouTube, TikTok, Instagram, Facebook & more. Free online video downloader with MP4, MP3, ZIP, and slideshow export. No watermark, no ads.',
    canonical: '/',
    h1: 'All-in-One Social Media Video, Audio & Photo Downloader',
    subtitle:
      'Paste a link from YouTube, TikTok, Instagram, Facebook, or X. Choose MP4 video, MP3 audio, PNG photo, or ZIP album — and save it instantly. Free, fast, and no watermark.',
    keywords:
      'social media video downloader, all in one video downloader, online video downloader free, youtube video downloader, tiktok downloader, instagram downloader, facebook video downloader',
    features: [
      {
        icon: 'Globe',
        title: 'Multi-Platform Support',
        description:
          'Download from YouTube, TikTok, Instagram, Facebook, X, and hundreds of other sites — all from one tool.',
      },
      {
        icon: 'FileVideo',
        title: 'Every Format You Need',
        description:
          'Choose MP4 video with resolution selection, MP3 audio with bitrate control, lossless PNG photos, or full-album ZIP archives.',
      },
      {
        icon: 'ListOrdered',
        title: 'Batch Download Queue',
        description:
          'Paste up to 50 links at once and download them all in parallel. Track progress for every item in a live visual queue.',
      },
      {
        icon: 'ShieldCheck',
        title: 'No Watermark, No Ads',
        description:
          'Every download is clean — no overlaid watermarks, no pop-up ads, no redirects. Just the original media file, ready to save.',
      },
    ],
    faqs: [
      {
        question: 'How do I download videos from social media?',
        answer:
          'Paste the public URL of any video from YouTube, TikTok, Instagram, Facebook, or X into the input field and click Continue. Choose your preferred format and quality, then click Download. The file saves through your browser\'s built-in download manager.',
      },
      {
        question: 'Is Snacky Studio completely free to use?',
        answer:
          'Yes. Snacky Studio is free for personal use. There are no hidden charges, premium tiers, or download limits when running the local or self-hosted version.',
      },
      {
        question: 'What platforms are supported?',
        answer:
          'Snacky Studio supports YouTube (including Shorts), TikTok, Instagram (posts, Reels, carousels), Facebook (videos, Reels, photos), X (formerly Twitter), and hundreds of additional sites powered by yt-dlp.',
      },
      {
        question: 'What output formats are available?',
        answer:
          'You can download video as MP4 in resolutions up to 4K 60fps, extract audio as MP3 at up to 320 kbps, save individual photos as lossless PNG, or download multi-image posts as a single ZIP archive.',
      },
      {
        question: 'How do I download multiple videos at once in a queue?',
        answer:
          'Switch to the Batch Links tab, paste up to 50 URLs (one per line), choose a default format and quality, and click Start Batch Download. Every link is queued and processed in parallel with live progress tracking.',
      },
    ],
  },

  // -----------------------------------------------------------------------
  // 2. TikTok slideshow + watermark-free
  // -----------------------------------------------------------------------
  {
    path: '/tiktok-slideshow-downloader',
    title: 'TikTok Slideshow to MP4 Converter & No-Watermark Video Downloader — Snacky Studio',
    metaDescription:
      'Convert TikTok photo slideshows to MP4 video with original music. Download TikTok videos without watermark in HD. Save TikTok carousel posts with audio.',
    canonical: '/tiktok-slideshow-downloader',
    h1: 'TikTok Photo Slideshow to MP4 & No-Watermark Video Downloader',
    subtitle:
      'Convert TikTok photo posts into smooth MP4 slideshows with the original soundtrack. Download any TikTok video in HD without watermark. Save carousel posts with audio intact.',
    keywords:
      'tiktok video downloader without watermark, tiktok photo slideshow to mp4 converter, download tiktok slideshow with music, tiktok carousel downloader with audio, tiktok downloader hd, save tiktok video, convert tiktok photo post to video',
    features: [
      {
        icon: 'Film',
        title: 'Slideshow → MP4 with Music',
        description:
          'Photo slideshows are rendered into a single MP4 video with images timed evenly over the original TikTok soundtrack — ready to share anywhere.',
      },
      {
        icon: 'ShieldOff',
        title: 'No Watermark Downloads',
        description:
          'Videos are saved without the TikTok watermark overlay, giving you a clean file at the original upload quality.',
      },
      {
        icon: 'Sparkles',
        title: 'Full HD Quality',
        description:
          'Downloads preserve the highest resolution available from TikTok, so you get sharp, crisp video without re-compression artifacts.',
      },
      {
        icon: 'Music',
        title: 'Original Audio Preserved',
        description:
          'Slideshow conversions keep the creator\'s chosen music track intact. If the soundtrack is available, it\'s embedded directly in the MP4.',
      },
    ],
    faqs: [
      {
        question: 'How do I download TikTok photo slideshows as a video with sound?',
        answer:
          'Paste the TikTok photo-post link and click Continue. If the post has an exposed soundtrack, Snacky Studio offers a "Slideshow · MP4" option that renders every photo over the original music into a single video file.',
      },
      {
        question: 'How do I download TikTok videos without a watermark?',
        answer:
          'Paste the video link, choose MP4 and your preferred resolution, then click Download. The saved file will not contain the TikTok username watermark that normally appears on-screen.',
      },
      {
        question: 'What quality are TikTok downloads?',
        answer:
          'Snacky Studio downloads the highest resolution available from TikTok for each video — typically 1080p or the original upload resolution. No extra compression is applied.',
      },
      {
        question: 'Can I download a TikTok carousel with the background music?',
        answer:
          'Yes. When a TikTok photo carousel has an audible soundtrack, the Slideshow · MP4 option combines all images with the music into a single video. Posts without music will show photo-only download options instead.',
      },
      {
        question: 'Does it work with private TikTok videos?',
        answer:
          'Snacky Studio can only access publicly available content. For private or friends-only TikTok posts you would need to provide a valid Netscape-format cookies file via the SNACKY_COOKIES_FILE setting.',
      },
    ],
  },

  // -----------------------------------------------------------------------
  // 3. Instagram carousel + Reels
  // -----------------------------------------------------------------------
  {
    path: '/instagram-carousel-downloader',
    title: 'Instagram Carousel to ZIP & Reels Video Downloader — Snacky Studio',
    metaDescription:
      'Download all photos from Instagram carousels as a ZIP file. Save Instagram Reels in HD MP4. Extract Instagram photos as lossless PNG. Free IG photo and video saver.',
    canonical: '/instagram-carousel-downloader',
    h1: 'Instagram Carousel to ZIP, Reels & Photo Downloader',
    subtitle:
      'Download every photo from an Instagram carousel as a single ZIP archive. Save Reels as HD MP4 video. Convert Instagram images to lossless PNG. All free, no login required.',
    keywords:
      'instagram carousel downloader zip, download multiple photos from instagram at once, instagram reels video download, ig photo and video saver, instagram downloader, convert social media photo to lossless png',
    features: [
      {
        icon: 'FolderArchive',
        title: 'Full Carousel → ZIP',
        description:
          'Every image in an Instagram carousel is downloaded in source order and bundled into a single ZIP archive with a post.json manifest — no partial downloads.',
      },
      {
        icon: 'Clapperboard',
        title: 'Reels in HD MP4',
        description:
          'Instagram Reels are saved as standard MP4 video at the highest available resolution, ready to watch or re-share offline.',
      },
      {
        icon: 'Image',
        title: 'Lossless PNG Conversion',
        description:
          'Save any Instagram photo as a lossless PNG, preserving decoded pixel dimensions without upscaling. Original-format saving is also available.',
      },
      {
        icon: 'LogIn',
        title: 'No Login Needed',
        description:
          'Public Instagram posts, Reels, and carousels can be downloaded without signing in to an Instagram account.',
      },
    ],
    faqs: [
      {
        question: 'How do I download all photos from an Instagram carousel as a ZIP file?',
        answer:
          'Paste the Instagram carousel post URL into Snacky Studio and click Continue. The app detects all images in the carousel and offers an "All photos · ZIP" option that packages every photo into one download.',
      },
      {
        question: 'Can I download Instagram Reels?',
        answer:
          'Yes. Paste the Reel\'s URL and choose MP4. The video is downloaded at the highest resolution Instagram provides, typically 1080p, and saved through your browser.',
      },
      {
        question: 'What is lossless PNG conversion?',
        answer:
          'When you choose "Save PNG", the original image is decoded and re-saved as a lossless PNG file. This preserves every pixel at decoded dimensions without upscaling, giving you a clean archival-quality image.',
      },
      {
        question: 'Do I need an Instagram account to download?',
        answer:
          'No account is needed for public posts. Private or friends-only content requires valid session cookies from an authorised account, configured via the SNACKY_COOKIES_FILE setting.',
      },
      {
        question: 'How many photos can I download from one Instagram carousel?',
        answer:
          'Snacky Studio supports carousels with up to 200 individual images. Each image can be up to 100 MB, and the total collection is capped at 2 GB to ensure reliable downloads.',
      },
    ],
  },

  // -----------------------------------------------------------------------
  // 4. YouTube video + MP3
  // -----------------------------------------------------------------------
  {
    path: '/youtube-video-mp3-downloader',
    title: 'YouTube Video Downloader 4K MP4 & 320kbps MP3 Audio Extractor — Snacky Studio',
    metaDescription:
      'Download YouTube videos in 4K, 1080p, 720p MP4. Extract high-quality 320kbps MP3 audio from YouTube. Download YouTube Shorts. Free HD video downloader.',
    canonical: '/youtube-video-mp3-downloader',
    h1: '4K YouTube Video & 320kbps MP3 Audio Downloader',
    subtitle:
      'Download any YouTube video in up to 4K 60fps MP4 with full resolution selection. Extract crystal-clear 320kbps MP3 audio. Download YouTube Shorts instantly. Free and unlimited.',
    keywords:
      'youtube video downloader hd, download youtube video mp4, youtube shorts downloader, youtube to mp3 320kbps high quality, extract audio from video online free, download video in 4k 60fps mp4, batch youtube playlist downloader',
    features: [
      {
        icon: 'MonitorPlay',
        title: '4K & HD Resolution Picker',
        description:
          'Choose from every available resolution — 4K 2160p, 1440p, 1080p, 720p, or the original upload quality. Video and audio streams are merged automatically by FFmpeg.',
      },
      {
        icon: 'Headphones',
        title: '320 kbps MP3 Extraction',
        description:
          'Extract the audio track from any YouTube video and encode it as a high-quality 320 kbps MP3 file. Multiple bitrate options (128, 192, 256, 320) are available.',
      },
      {
        icon: 'Smartphone',
        title: 'YouTube Shorts Support',
        description:
          'Short-form vertical videos download just as easily — paste the Shorts URL and save as MP4 or extract the audio as MP3.',
      },
      {
        icon: 'List',
        title: 'Batch & Playlist Downloads',
        description:
          'Use the Batch Links tab to paste multiple YouTube URLs at once. Each video is queued and downloaded in parallel with individual progress tracking.',
      },
    ],
    faqs: [
      {
        question: 'How do I extract 320 kbps MP3 audio from a YouTube video?',
        answer:
          'Paste the YouTube video URL, click Continue, then select MP3 as the output format and choose 320 kbps from the bitrate options. Click Download and the audio file will be saved through your browser\'s download manager.',
      },
      {
        question: 'What video resolutions are available for YouTube downloads?',
        answer:
          'The available resolutions depend on the original upload. Snacky Studio lists every option the source provides — commonly 360p, 480p, 720p, 1080p, 1440p, and 2160p (4K). An "Original" option is also available when the exact resolution is unknown.',
      },
      {
        question: 'Can I download YouTube Shorts?',
        answer:
          'Yes. Paste the YouTube Shorts URL exactly as you would a regular video. Snacky Studio recognises the format and offers the same MP4 and MP3 options.',
      },
      {
        question: 'Can I download an entire YouTube playlist at once?',
        answer:
          'Snacky Studio\'s Batch Links tab lets you paste multiple individual video URLs. While it doesn\'t auto-expand a playlist URL, you can paste each video link from a playlist to download them all in parallel.',
      },
      {
        question: 'Is downloading YouTube videos legal?',
        answer:
          'Downloading content you have the right to access for personal, offline use is generally permitted in many jurisdictions. Always respect copyright and the creator\'s terms. Snacky Studio is a tool — how you use it is your responsibility.',
      },
    ],
  },

  // -----------------------------------------------------------------------
  // 5. Facebook video + Reels
  // -----------------------------------------------------------------------
  {
    path: '/facebook-reels-video-downloader',
    title: 'Facebook HD Video & Reels Downloader — Download FB Videos Free — Snacky Studio',
    metaDescription:
      'Download Facebook videos in HD quality. Save Facebook Reels as MP4. Download public Facebook group videos. Free FB video downloader with no watermark or ads.',
    canonical: '/facebook-reels-video-downloader',
    h1: 'Facebook HD Video & Reels Downloader',
    subtitle:
      'Save any public Facebook video or Reel in full HD MP4. Download from Facebook pages, groups, and profiles. Extract Facebook photos and photo albums. No watermark, completely free.',
    keywords:
      'facebook video downloader hd, fb reels downloader, download private facebook video, facebook video downloader, fb video download, download facebook reels',
    features: [
      {
        icon: 'MonitorPlay',
        title: 'HD Video Downloads',
        description:
          'Facebook videos are saved at the highest quality available — typically HD or Full HD MP4, exactly as uploaded by the creator.',
      },
      {
        icon: 'PlayCircle',
        title: 'Facebook Reels',
        description:
          'Download Facebook Reels as standard MP4 files. Short-form video is saved at full resolution without compression or watermarks.',
      },
      {
        icon: 'Users',
        title: 'Pages, Groups & Profiles',
        description:
          'Download public videos from Facebook Pages, Groups, and personal profiles. Any publicly accessible Facebook video URL will work.',
      },
      {
        icon: 'ImageDown',
        title: 'Photo Album Extraction',
        description:
          'Save individual Facebook photos or extract multi-photo posts. Single images can be converted to lossless PNG; collections are bundled into ZIP.',
      },
    ],
    faqs: [
      {
        question: 'How do I download Facebook videos in HD?',
        answer:
          'Paste the Facebook video URL into Snacky Studio and click Continue. The tool automatically detects available qualities and lets you choose the highest HD resolution before downloading.',
      },
      {
        question: 'Can I download Facebook Reels?',
        answer:
          'Yes. Copy the Reel\'s URL from Facebook, paste it into Snacky Studio, and download it as an MP4. The video is saved at full resolution without any watermark.',
      },
      {
        question: 'Can I download private Facebook videos?',
        answer:
          'Private videos require valid session cookies from a Facebook account that has permission to view the content. Set the SNACKY_COOKIES_FILE environment variable to a Netscape-format cookies file from your authorized session.',
      },
      {
        question: 'Do Facebook Group videos work?',
        answer:
          'Yes, as long as the Group post is publicly accessible or you provide cookies from an account that is a member of the Group. Paste the post or video URL and download as usual.',
      },
      {
        question: 'Is this the best free video downloader without watermark or pop-up ads?',
        answer:
          'Snacky Studio downloads the original media file without adding watermarks, overlays, or advertisements. There are no pop-ups, no redirects, and no hidden subscriptions. Files save directly through your browser.',
      },
    ],
  },

  // -----------------------------------------------------------------------
  // 6. Batch + self-hosted + desktop
  // -----------------------------------------------------------------------
  {
    path: '/batch-media-downloader',
    title: 'Batch Link Queue & Self-Hosted Media Downloader — yt-dlp Web UI — Snacky Studio',
    metaDescription:
      'Download multiple videos at once with a batch queue. Self-hosted Docker media downloader with yt-dlp and gallery-dl web interface. Open-source desktop app with Tauri.',
    canonical: '/batch-media-downloader',
    h1: 'Batch Link Queue & Self-Hosted Media Downloader',
    subtitle:
      'Paste up to 50 links and download them all in parallel with a visual queue. Self-host with Docker for unlimited private downloads. Desktop app available via Tauri. Powered by yt-dlp and gallery-dl.',
    keywords:
      'batch youtube playlist downloader, multi-link video downloader queue, yt-dlp web ui, gallery-dl web interface, self-hosted social media downloader docker, open source desktop video downloader app, tauri media downloader gui',
    features: [
      {
        icon: 'ListOrdered',
        title: 'Batch Queue (Up to 50 Links)',
        description:
          'Paste multiple URLs in the Batch Links tab — each one is queued, processed in parallel, and tracked with individual progress bars, speed, and ETA.',
      },
      {
        icon: 'Container',
        title: 'Docker Self-Hosted',
        description:
          'Deploy Snacky Studio on your own server with Docker Compose. PostgreSQL, Redis, Celery workers, and S3-compatible storage run in isolated containers with one command.',
      },
      {
        icon: 'Monitor',
        title: 'Tauri Desktop App',
        description:
          'Install Snacky Studio as a native desktop application for Windows, macOS, and Linux. The Tauri build bundles a frozen Python sidecar with FFmpeg — no browser tab needed.',
      },
      {
        icon: 'Terminal',
        title: 'Powered by yt-dlp & gallery-dl',
        description:
          'The same battle-tested engines trusted by power users. yt-dlp handles video extraction from 1,000+ sites; gallery-dl handles photo posts and carousels.',
      },
    ],
    faqs: [
      {
        question: 'How do I download multiple videos at once in a queue?',
        answer:
          'Click the Batch Links tab, paste up to 50 URLs (one per line), choose your default format and quality, and click Start Batch Download. All links are queued and processed simultaneously.',
      },
      {
        question: 'What is self-hosted mode?',
        answer:
          'Self-hosted (cloud) mode runs Snacky Studio on your own server using Docker Compose. It adds PostgreSQL for persistent job state, Redis for task queuing, Celery workers for parallel processing, and S3-compatible storage for completed files — ideal for teams.',
      },
      {
        question: 'What is yt-dlp web UI?',
        answer:
          'Snacky Studio provides a modern React web interface on top of yt-dlp and gallery-dl — the open-source command-line tools for downloading media. You get a visual UI with progress tracking instead of running terminal commands.',
      },
      {
        question: 'How do I install the desktop app?',
        answer:
          'Download the Tauri installer for your platform (Windows .msi, macOS .dmg, or Linux .AppImage) from the releases page. The desktop build includes a bundled Python runtime and FFmpeg so no extra setup is needed.',
      },
      {
        question: 'Is Snacky Studio open source?',
        answer:
          'Snacky Studio\'s core is built on open-source tools (yt-dlp, gallery-dl, FFmpeg, FastAPI, React). Check the project repository for licence details and contribution guidelines.',
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Lookup helper
// ---------------------------------------------------------------------------

export function getSeoRoute(pathname: string): SeoRoute {
  return seoRoutes.find((r) => r.path === pathname) || seoRoutes[0];
}

