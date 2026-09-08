import type { Config } from 'tailwindcss';
import sharedConfig from '@meghdrishti/ui/tailwind.config';

const config: Config = {
  ...sharedConfig,
  content: [
    ...(sharedConfig.content || []),
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
};

export default config;
