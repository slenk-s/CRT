/** 前端压缩：长边 ≤ maxEdge，JPEG 质量 0.85；失败或未缩小时回退原文件。 */

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('图片解码失败'))
    }
    img.src = url
  })
}

export async function compressImage(file: File, maxEdge = 1920, quality = 0.85): Promise<File> {
  if (!file.type.startsWith('image/') || file.type === 'image/gif') return file
  try {
    const img = await loadImage(file)
    const ratio = Math.min(1, maxEdge / Math.max(img.width, img.height))
    if (ratio >= 1 && file.size <= 2 * 1024 * 1024) return file

    const w = Math.round(img.width * ratio)
    const h = Math.round(img.height * ratio)
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(img, 0, 0, w, h)

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/jpeg', quality),
    )
    if (!blob || blob.size >= file.size) return file
    const name = `${file.name.replace(/\.[^.]+$/, '')}.jpg`
    return new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() })
  } catch {
    return file
  }
}