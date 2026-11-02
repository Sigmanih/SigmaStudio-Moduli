import React, { useEffect, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';

export default function CreativeSkills({ onOpen }) {
  const [skills, setSkills] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/creative/skills', { signal: controller.signal }).then(r => r.json()).then(data => {
      if (!data.success) throw new Error(data.error || 'Skill non disponibili');
      setSkills(data.skills || []);
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, []);
  if (error) return <p className="cs-form-notice" role="alert">{error}</p>;
  return <section aria-label="Skill creative" data-agent-component="CreativeSkills" data-agent-id="creative-skills"><h3>Competenze governabili, anche dalla chat</h3><div className="cs-skills-grid">{skills.map(skill => <article key={skill.id}><h4>{skill.label}</h4><p>{skill.description}</p><dl><dt>Occorre</dt><dd>{skill.inputs.join(' · ')}</dd><dt>Risultato</dt><dd>{skill.outputs.join(' · ')}</dd></dl><details><summary>Istruzioni e controlli</summary><div className="cs-skill-instructions">{(skill.instructions || '').replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '').trim()}</div></details><button className="cs-text-button" onClick={() => onOpen(skill.id)}><ArrowUpRight size={14} /> Apri lo strumento</button></article>)}</div></section>;
}
