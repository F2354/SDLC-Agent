import { create } from 'zustand'

interface AuthState {
  token: string | null
  setToken: (token: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('sdlc_token'),
  setToken: (token) => {
    localStorage.setItem('sdlc_token', token)
    set({ token })
  },
  logout: () => {
    localStorage.removeItem('sdlc_token')
    set({ token: null })
  },
}))
