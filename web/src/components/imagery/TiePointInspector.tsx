import { useEffect, useState } from 'react'
import type { TiePoint } from '@/types/tiepoint'
import { MetadataGrid } from '@/components/ui/MetadataGrid'

const PATCH_SIZE = 72

function cropPatch(imageUrl: string, x: number, y: number): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = PATCH_SIZE
      canvas.height = PATCH_SIZE
      const ctx = canvas.getContext('2d')
      if (!ctx) return resolve('')
      ctx.imageSmoothingEnabled = false
      ctx.drawImage(img, x - PATCH_SIZE / 2, y - PATCH_SIZE / 2, PATCH_SIZE, PATCH_SIZE, 0, 0, PATCH_SIZE, PATCH_SIZE)
      resolve(canvas.toDataURL())
    }
    img.src = imageUrl
  })
}

interface TiePointInspectorProps {
  tiePoint: TiePoint
  sourceImageUrl: string
  referenceImageUrl: string
}

export function TiePointInspector({ tiePoint, sourceImageUrl, referenceImageUrl }: TiePointInspectorProps) {
  const [patches, setPatches] = useState<{ source: string; reference: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      cropPatch(sourceImageUrl, tiePoint.source.x, tiePoint.source.y),
      cropPatch(referenceImageUrl, tiePoint.reference.x, tiePoint.reference.y),
    ]).then(([source, reference]) => {
      if (!cancelled) setPatches({ source, reference })
    })
    return () => {
      cancelled = true
    }
  }, [tiePoint.id, sourceImageUrl, referenceImageUrl, tiePoint.source.x, tiePoint.source.y, tiePoint.reference.x, tiePoint.reference.y])

  return (
    <div>
      <div className="text-section-title">TIEPOINT {tiePoint.id}</div>

      {patches && (
        <div className="mt-3 flex gap-2">
          <div>
            <img src={patches.source} width={PATCH_SIZE} height={PATCH_SIZE} alt="Source patch" className="border border-hairline" />
            <div className="mt-1 text-center text-micro text-mute">SOURCE</div>
          </div>
          <div>
            <img src={patches.reference} width={PATCH_SIZE} height={PATCH_SIZE} alt="Reference patch" className="border border-hairline" />
            <div className="mt-1 text-center text-micro text-mute">REFERENCE</div>
          </div>
        </div>
      )}

      <div className="mt-4">
        <MetadataGrid
          entries={[
            { label: 'Source x', value: tiePoint.source.x.toFixed(3) },
            { label: 'Source y', value: tiePoint.source.y.toFixed(3) },
            { label: 'Reference x', value: tiePoint.reference.x.toFixed(3) },
            { label: 'Reference y', value: tiePoint.reference.y.toFixed(3) },
            { label: 'Residual', value: `${tiePoint.residualPx.toFixed(2)} px` },
            { label: 'Confidence', value: tiePoint.confidence.toFixed(2) },
          ]}
        />
      </div>

      <div className="mt-4 border-t border-hairline pt-3">
        <div className="text-micro font-medium uppercase tracking-wide text-mute">Covariance</div>
        <MetadataGrid
          columns={1}
          entries={[
            { label: 'σx', value: tiePoint.covariance.sigmaX.toFixed(3) },
            { label: 'σy', value: tiePoint.covariance.sigmaY.toFixed(3) },
            { label: 'ρ', value: tiePoint.covariance.rho.toFixed(3) },
          ]}
        />
      </div>
    </div>
  )
}
