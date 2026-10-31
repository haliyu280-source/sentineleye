import { createContext, useContext } from 'react'

// Who is looking at the dashboard:
//   publicMode  the backend lets anyone view (SENTINELEYE_PUBLIC_DASHBOARD)
//   isAdmin     signed in with the admin token, so management controls are shown
export const AccessContext = createContext({ ready: false, publicMode: false, isAdmin: false })

export function useAccess() {
  return useContext(AccessContext)
}
