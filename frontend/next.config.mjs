import withPWA from '@ducanh2912/next-pwa';

const isExport = process.env.NEXT_PUBLIC_EXPORT === "true"
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || ""

/** @type {import('next').NextConfig} */
const nextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  output: isExport ? "export" : undefined,
  trailingSlash: true,
  basePath: isExport ? basePath : undefined,
  assetPrefix: isExport && basePath ? `${basePath}/` : undefined,
}

export default withPWA({
  dest: 'public',
  disable: process.env.NODE_ENV === 'development' || isExport,
  register: true,
  skipWaiting: true,
  fallbacks: {
    document: `${basePath}/offline`,
  },
  workboxOptions: {
    runtimeCaching: [
      {
        urlPattern: /^https?.*/,
        handler: 'NetworkFirst',
        options: {
          cacheName: 'offlineCache',
          expiration: {
            maxEntries: 200,
          },
        },
      },
    ],
  },
})(nextConfig);
