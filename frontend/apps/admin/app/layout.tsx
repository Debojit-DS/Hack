import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Meghdrishti Admin',
  description: 'Tactical Command Dashboard',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="admin">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
