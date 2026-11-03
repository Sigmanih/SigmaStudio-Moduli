import React from 'react';
import CreationForm from './CreationForm';
import CreationResults from './CreationResults';

export default function GeneratePanel({
  onGenerate, onUpload, isGenerating, recentAssets = [], onSelectAsset, onEditAsset, onReuseAsset, onDeleteAsset,
  backends = [], models = [], inventory = null, draft, onDraftChange, selectedAsset,
  loading, modelError, onRefreshModels, onManageModels,
}) {
  const activeAsset = recentAssets.find(a => a.id === selectedAsset?.id) || recentAssets[0];
  return <div className="cs-image-workspace" data-agent-component="GeneratePanel" data-agent-id="creative-2d-generator">
    <CreationForm draft={draft} onChange={onDraftChange} onGenerate={onGenerate} busy={isGenerating}
      backends={backends} models={models} inventory={inventory} loading={loading} error={modelError}
      onRefresh={onRefreshModels} onManageModels={onManageModels} />
    <CreationResults asset={activeAsset} assets={recentAssets} busy={isGenerating}
      onSelect={onSelectAsset} onEdit={onEditAsset} onReuse={onReuseAsset} onUpload={onUpload} onDelete={onDeleteAsset} />
  </div>;
}
