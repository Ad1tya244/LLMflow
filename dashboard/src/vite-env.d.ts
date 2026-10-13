/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_GATEWAY_URL?: string;
  /** Injected by `npm run dev` only; ignored in production builds. */
  readonly VITE_DEV_API_KEY?: string;
}
