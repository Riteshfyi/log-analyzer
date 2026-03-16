# PWA Icons Required

To complete the PWA setup, you need to create and add the following icon files to this directory:

## Required Icons

1. **icon-192x192.png** - Standard app icon (192x192 pixels)
2. **icon-512x512.png** - High-res app icon (512x512 pixels)
3. **icon-192x192-maskable.png** - Maskable icon for adaptive icons (192x192 pixels)
4. **icon-512x512-maskable.png** - High-res maskable icon (512x512 pixels)
5. **favicon.ico** - Browser favicon
6. **apple-touch-icon.png** - Apple devices icon (180x180 pixels recommended)

## How to Create Icons

### Option 1: Using Online Tools
- **PWA Asset Generator**: https://www.pwabuilder.com/imageGenerator
- Upload a square logo (1024x1024 recommended)
- It will generate all required sizes

### Option 2: Manual Creation
- Use design tools (Figma, Photoshop, etc.)
- Create icons with your app logo/branding
- Export at the specified sizes
- For maskable icons, ensure the safe zone (80% center area) contains all important content

## Maskable Icons
Maskable icons need extra padding because they can be cropped into various shapes (circle, squircle, etc.) by different devices. The important content should be in the center 80% of the image.

## Quick Start
Until you create proper icons, you can:
1. Rename one of your placeholder images to match the required names
2. Use an online tool to resize it to the required dimensions
3. This will allow PWA installation to work (though with placeholder branding)

## Current Placeholders
The manifest.json currently references these icon paths. Make sure to create them!
