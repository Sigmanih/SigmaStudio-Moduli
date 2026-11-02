import React from 'react';
import { FolderOpen } from 'lucide-react';

export default function CreativeEmptyState({ icon: Icon, title, description, onChoose }) {
  return <section className="cs-creative-empty" data-agent-component="CreativeEmptyState" data-agent-id="creative-empty-state"><Icon size={42} strokeWidth={1.2} /><h2>{title}</h2><p>{description}</p>{onChoose && <button className="cs-secondary-button" onClick={onChoose}><FolderOpen size={16} /> Apri la libreria</button>}</section>;
}
