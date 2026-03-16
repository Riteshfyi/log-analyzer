import type { Metadata, Viewport } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Microservice Log Analyzer',
  description: 'Analyze and visualize microservice logs with AI-powered insights',
  generator: 'Next.js',
  applicationName: 'Microservice Log Analyzer',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'default',
    title: 'Log Analyzer',
  },
  formatDetection: {
    telephone: false,
  },
  openGraph: {
    type: 'website',
    siteName: 'Microservice Log Analyzer',
    title: 'Microservice Log Analyzer',
    description: 'Analyze and visualize microservice logs with AI-powered insights',
  },
  twitter: {
    card: 'summary',
    title: 'Microservice Log Analyzer',
    description: 'Analyze and visualize microservice logs with AI-powered insights',
  },
  manifest: '/manifest.json',
  icons: {
    icon: '/icon-192x192.png',
    apple: '/apple-touch-icon.png',
  },
}

export const viewport: Viewport = {
  themeColor: '#000000',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
