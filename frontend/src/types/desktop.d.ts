export {};

declare global {
  interface Window {
    bidDesignWriterDesktop?: {
      platform: string;
      selectDirectory: () => Promise<{ name: string; path: string } | null>;
      getAppAuthSecret: () => Promise<string>;
      getBackendUrl: () => Promise<string>;
    };
  }
}
