import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MediaPreview } from '@/components/MediaPreview';
import { Progress } from '@/components/ui/progress';
import type { MediaInfo } from '@/types';
const photo:MediaInfo={url:'https://www.facebook.com/photo?fbid=123',id:'123',title:'A photo',uploader:'Creator',duration:'1 photo',duration_seconds:0,platform:{name:'Facebook',id:'facebook'},media_type:'photos',photo_count:1,has_music:false,qualities:[],audio_qualities:[]};
describe('photo and output choices',()=>{
 it('offers original and PNG downloads for a single photo',async()=>{
  const download=vi.fn();render(<MediaPreview info={photo} format="photos" quality="best" busy={false} onFormat={()=>{}} onQuality={()=>{}} onDownload={download}/>);
  await userEvent.click(screen.getByRole('button',{name:'Save PNG'}));expect(download).toHaveBeenCalledWith('png');expect(screen.getByRole('button',{name:'Save photo'})).toBeEnabled();
 });
 it('disables a music slideshow when the soundtrack is unavailable',()=>{
  render(<MediaPreview info={{...photo,photo_count:3}} format="photos" quality="best" busy={false} onFormat={()=>{}} onQuality={()=>{}} onDownload={()=>{}}/>);
  expect(screen.getByRole('button',{name:'Slideshow · MP4'})).toBeDisabled();
 });
 it('exposes the actual preparation percentage to assistive technology',()=>{
  render(<Progress aria-label="Preparing video" value={37}/>);expect(screen.getByRole('progressbar',{name:'Preparing video'})).toHaveAttribute('aria-valuenow','37');
 });
});
