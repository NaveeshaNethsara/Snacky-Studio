import { Download, Film, ImageIcon, Music2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { safeImage } from '@/lib/api';
import type { Format, MediaInfo } from '@/types';

interface Props { info: MediaInfo; format: Format; quality: string; busy: boolean; onFormat: (format: Format) => void; onQuality: (quality: string) => void; onDownload: (format?: Format) => void }
export function MediaPreview({info, format, quality, busy, onFormat, onQuality, onDownload}: Props) {
  const photos = info.media_type === 'photos', single = photos && info.photo_count === 1 && !info.has_music;
  const thumbnail = safeImage(info.thumbnail);
  const choices = format === 'mp3' ? info.audio_qualities : info.qualities;
  const options: {id: Format; label: string; icon: typeof Film}[] = photos
    ? [{id:'photos',label:'All photos · ZIP',icon:ImageIcon},{id:'slideshow',label:'Slideshow · MP4',icon:Film}]
    : [{id:'mp4',label:'Video · MP4',icon:Film},{id:'mp3',label:'Audio · MP3',icon:Music2}];
  return <section className="media-preview" aria-label="Media preview">
    <div className={`preview-summary ${single ? 'single-photo' : ''}`}>
      <div className="thumbnail">{thumbnail ? <img src={thumbnail} alt={single ? info.title : 'Media preview'} referrerPolicy="no-referrer" onError={e => {e.currentTarget.style.visibility='hidden';}}/> : <Film size={32}/>}<span>{info.duration}</span></div>
      <div className="preview-copy"><span className="platform-badge">{info.platform.name}</span><h2>{info.title}</h2><p>{info.uploader}</p>
        {single && <div className="photo-actions"><Button className="gradient-button" disabled={busy} onClick={() => onDownload('photo')}><Download/>Save photo</Button><Button variant="outline" disabled={busy} onClick={() => onDownload('png')}>Save PNG</Button></div>}
      </div>
    </div>
    {photos && !single && <div className="photo-grid" aria-label="Photos in this post">{info.photos?.map((photo,index) => <div key={index}><img src={safeImage(photo.url)} alt={`Photo ${index+1}`} loading="lazy" referrerPolicy="no-referrer"/><span>{index+1}</span></div>)}</div>}
    {!single && <><div className="output-row">
      <div className="format-buttons" role="group" aria-label="Output format">{options.map(option => <Button key={option.id} className="format-option" data-format={option.id} variant={format === option.id ? 'secondary' : 'ghost'} aria-pressed={format === option.id} disabled={busy || (option.id === 'slideshow' && !info.has_music)} onClick={() => onFormat(option.id)}><option.icon size={20} aria-hidden="true"/>{option.label}</Button>)}</div>
      {format !== 'photos' && <label className="quality-label">{format === 'mp3' ? 'Bitrate' : 'Quality'}<select aria-label={format === 'mp3' ? 'Bitrate' : 'Quality'} value={quality} disabled={busy} onChange={e => onQuality(e.target.value)}>{choices.map(choice => <option key={choice.id} value={choice.id}>{choice.id === 'best' && format !== 'slideshow' ? 'Original' : choice.badge}</option>)}</select></label>}
      <Button className="gradient-button download-cta" disabled={busy} onClick={() => onDownload()}><Download size={16}/>{busy ? 'Starting…' : format === 'photos' ? 'Download all photos' : format === 'slideshow' ? 'Download slideshow' : 'Download'}</Button>
    </div><p className="quiet-note">{photos ? format === 'slideshow' ? `Photos play in order with ${info.music?.title || 'the original music'}.` : `${info.photo_count} photos, saved in their original quality.${!info.has_music ? ' Original music is unavailable for this post.' : ''}` : format === 'mp3' ? 'Bitrate sets the encoding quality; source quality stays the same.' : 'We prepare your file, then save it through your browser.'}</p></>}
  </section>;
}
