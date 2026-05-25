import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

const ScreenNode = memo(({ data, selected }) => {
  const snapshotId = data.first_snapshot_id;
  const direction = data.direction ?? 'LR';
  const isVertical = direction === 'LR';

  const imageUrl = snapshotId
    ? (
      data.blobUrlMap?.[snapshotId] ??
      (data.jsonPath
        ? `/api/snapshot?jsonPath=${encodeURIComponent(data.jsonPath)}&id=${snapshotId}`
        : null)
    )
    : null;

  const handleOpenPreview = (e) => {
    e.stopPropagation();
    data.onOpenPreview?.(e);
  };

  return (
    <div
      className={`screen-node ${selected ? 'selected' : ''}`}
      onClick={handleOpenPreview}
      style={{ cursor: 'pointer' }}
    >
      {/* 입력 핸들 */}
      {isVertical ? (
        <Handle
          type="target"
          position={Position.Top}
          style={{
            left: '50%',
            top: 0,
            transform: 'translate(-50%, -50%)',
          }}
        />
      ) : (
        <Handle
          type="target"
          position={Position.Left}
          style={{
            left: 0,
            top: '50%',
            transform: 'translate(-50%, -50%)',
          }}
        />
      )}

      {/* 스냅샷 이미지 */}
      <div className="node-image-wrap">
        {imageUrl ? (
          <>
            <img
              src={imageUrl}
              alt={`Screen ${data.index}`}
              loading="lazy"
              onError={e => {
                e.currentTarget.style.display = 'none';
                if (e.currentTarget.nextElementSibling) {
                  e.currentTarget.nextElementSibling.style.display = 'flex';
                }
              }}
            />
            <div className="node-no-image" style={{ display: 'none' }}>
              📱<span>no image</span>
            </div>
          </>
        ) : (
          <div className="node-no-image">
            📱<span>no image</span>
          </div>
        )}
      </div>

      {/* 노드 정보 */}
      <div className="node-info">
        <div className="node-index">#{data.index}</div>
        <div className="node-id" title={data.screen_id}>
          {data.screen_id}
        </div>
        <div className="node-meta">
          <span className="node-tag">
            📷 {data.snapshots?.length ?? 0}
          </span>
          {snapshotId && (
            <span className="node-tag">{snapshotId}</span>
          )}
        </div>
      </div>

      {/* 출력 핸들 */}
      {!isVertical ? (
        <Handle
          type="source"
          position={Position.Bottom}
          style={{
            left: '50%',
            bottom: 0,
            transform: 'translate(-50%, 50%)',
          }}
        />
      ) : (
        <Handle
          type="source"
          position={Position.Right}
          style={{
            right: 0,
            top: '50%',
            transform: 'translate(50%, -50%)',
          }}
        />
      )}
    </div>
  );
});

ScreenNode.displayName = 'ScreenNode';
export default ScreenNode;