// MapLibre draws with WebGL; without it (e.g. hardware acceleration turned off) the map can't start.
export const webglSupported = (() => {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
})()
