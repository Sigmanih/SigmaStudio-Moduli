import React from 'react';
import PcbLab from './PcbLab';
import './styles/pcb-lab.css';


// Da non confondere con Hardware Lab: quello osserva come gli agenti usano
// la macchina, questo progetta circuiti stampati con KiCad.
export default function PcbLabModule(props) {
  return <PcbLab {...props} />;
}

export { PcbLab };
