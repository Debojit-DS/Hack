import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Meghdrishti Portal',
  description: 'Citizen Survival Portal',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="citizen-online">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
