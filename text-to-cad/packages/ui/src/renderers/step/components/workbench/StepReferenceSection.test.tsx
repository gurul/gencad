import React from 'react';
import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useStepReferenceChips} from '../../../../../dist/renderers/step/components/workbench/StepReferenceSection.js';
Object.assign(globalThis,{React});
afterEach(()=>{cleanup();vi.restoreAllMocks();});

// The chips as Quick Edit draws them, each its name over its card's rows.
function Chips(props:any){
 const chips=useStepReferenceChips(props);
 return <>{chips.map((chip:any)=><section key={chip.key} aria-label={chip.label}><h3>{chip.label}</h3>{chip.card}</section>)}</>;
}
const names=()=>screen.queryAllByRole('heading').map(heading=>heading.textContent);
// A chip's rows, label then value, in order.
const rows=(name?:string)=>[...(name ? screen.getByRole('region',{name}) : document).querySelectorAll('[data-info-row]')].map(row=>row.textContent);
const arc={id:'o1.e1',normalizedSelector:'o1.e1',selectorType:'edge',pickData:{curveType:'circle',length:7.8,params:{radius:5,sweepRadians:Math.PI/2,center:[0,0,0]},center:[3,3,0]}};

it("an edge's chip carries its key measurements alone: an arc's diameter, radius, arc length and sweep",()=>{
 render(<Chips references={[arc]}/>);
 expect(names()).toEqual(['o1 · edge 1']);
 expect(rows()).toEqual(['Diameter Ø10 mm','Radius R5 mm','Arc length7.85 mm','Sweep angle90 °']);
 for (const gone of ['Center','o1.e1']) expect(screen.queryByText(gone),gone).toBeNull();
});

it('several picks of one kind on one part are ONE chip, its card a row each: a long or grouped selection never floods the box',()=>{
 const edges=[3,4,5].map((length,i)=>({id:`o1.e${i}`,selectorType:'edge',normalizedSelector:`o1.e${i}`,occurrenceId:'o1',pickData:{curveType:'line',length}}));
 const face={id:'o1.f2',normalizedSelector:'o1.f2',selectorType:'face',occurrenceId:'o1',pickData:{surfaceType:'plane',area:12}};
 const other={id:'o2.e1',normalizedSelector:'o2.e1',selectorType:'edge',occurrenceId:'o2',pickData:{curveType:'line',length:9}};
 render(<Chips references={[...edges,face,other]}/>);
 // In the order first picked: the run of edges, the face, the other part's edge.
 expect(names()).toEqual(['o1 · 3 edges','o1 · face 2','o2 · edge 1']);
 expect(rows('o1 · 3 edges')).toEqual(['edge 03 mm','edge 14 mm','edge 25 mm']);
});

it("a face's chip carries its area, and a round one's its radii: nothing of its kind, id, place or part",()=>{
 const face={id:'o1.f2',normalizedSelector:'o1.f2',selectorType:'face',pickData:{surfaceType:'plane',area:662.734,center:[2,4,6],normal:[0,0,1],sourceName:'Camera',bbox:{min:[0,0,0],max:[40,20,0]}}};
 const {rerender}=render(<Chips references={[face]}/>);
 expect(names()).toEqual(['Camera · face 2']);
 expect(rows()).toEqual(['Area662.73 mm²']);
 for (const gone of ['Type','ID','o1.f2','Center','Normal','Size','Component']) expect(screen.queryByText(gone),gone).toBeNull();
 rerender(<Chips references={[{...face,pickData:{...face.pickData,surfaceType:'cylinder',area:94.25,params:{radius:3}}}]}/>);
 expect(rows()).toEqual(['Diameter Ø6 mm','Radius R3 mm','Area94.25 mm²']);
});

it('a component or subassembly is a chip of its own, by its name, its card its parts and size: never its id',()=>{
 const name='camera_assembly_with_a_name_that_exceeds_the_panel_width';
 const selector='o1.8.1234567890.1234567890.1234567890.1234567890';
 const camera={id:selector,nodeType:'assembly',name,leafPartIds:['camera','mount'],children:[],bbox:{min:[0,0,0],max:[10,20,30]}};
 const base={id:'o1.1',nodeType:'part',name:'Base',leafPartIds:['o1.1'],children:[],bbox:{min:[0,0,0],max:[40,29,10]}};
 render(<Chips references={[base,camera]}/>);
 expect(names()).toEqual(['Base',name]);
 expect(rows(name)).toEqual(['Parts2','Size10 × 20 × 30 mm']);
 expect(rows('Base')).toEqual(['Size40 × 29 × 10 mm']);
 expect(screen.queryByText(selector)).toBeNull();
});

it("a part's chip shows its own Volume and, without a box of its own, its parts' size",()=>{
 // Two 10 mm cubes, as a mesh part's triangles: the volume is read off the displayed mesh.
 const cube=(id:string)=>({id,nodeType:'part',name:id,leafPartIds:[id],children:[],bbox:{min:[0,0,0],max:[10,10,10]}});
 const box=[[0,0,0],[10,0,0],[10,10,0],[0,10,0],[0,0,10],[10,0,10],[10,10,10],[0,10,10]].flat();
 const faces=[0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,1,2,6,1,6,5,2,3,7,2,7,6,3,0,4,3,4,7];
 const meshData={vertices:new Float32Array([...box,...box]),indices:new Uint32Array([...faces,...faces.map(i=>i+8)]),
  parts:[{id:'a',occurrenceId:'a',vertexOffset:0,vertexCount:8,triangleOffset:0,triangleCount:12},{id:'b',occurrenceId:'b',vertexOffset:8,vertexCount:8,triangleOffset:12,triangleCount:12}]};
 render(<Chips references={[cube('a'),cube('b')]} meshData={meshData}/>);
 expect(screen.getAllByText('1,000 mm³')).toHaveLength(2);
 cleanup();
 const part=(id:string)=>({id,nodeType:'part',name:id,leafPartIds:[id],children:[]});
 const sizes:Record<string,number[]>={a:[10,10,10],b:[40,20,5]};
 render(<Chips references={[part('a'),part('b')]} partsSize={(ids:string[])=>ids.length===1 ? sizes[ids[0]] : null}/>);
 expect([rows('a'),rows('b')]).toEqual([['Size10 × 10 × 10 mm'],['Size40 × 20 × 5 mm']]);
});

it('names a face or edge by its own label, else by its part and kind, never by its raw id',()=>{
 const meshData={parts:[{id:'o1.1',occurrenceId:'o1.1',name:'base'}]};
 const named={id:'topology|o1.1|face|o1.1.f3',normalizedSelector:'o1.1.f3',selectorType:'face',occurrenceId:'o1.1',label:'Mounting face',pickData:{surfaceType:'plane'}};
 const {rerender}=render(<Chips references={[named]} meshData={meshData}/>);
 expect(names()).toEqual(['Mounting face']);
 rerender(<Chips references={[{...named,label:undefined}]} meshData={meshData}/>);
 expect(names()).toEqual(['base · face 3']);
 rerender(<Chips references={[{id:'topology|o1.1|edge|o1.1.e4',normalizedSelector:'o1.1.e4',selectorType:'edge',occurrenceId:'o1.1',pickData:{curveType:'line',length:2}}]} meshData={meshData}/>);
 expect(names()).toEqual(['base · edge 4']);
 expect(rows()).toEqual(['Length2 mm']);
 expect(screen.queryByText('o1.1.e4')).toBeNull();
});

it('names the part of a single-part file with no name of its own after the file',()=>{
 // A part the STEP gave no name goes by its occurrence id in the tree, and the tree's root is the
 // part, named after the file.
 const meshData={parts:[{id:'o1.1',occurrenceId:'o1.1',name:'o1.1'}]};
 const root=new Map([['__step_model__','l_bracket.step']]);
 const partName=(id:string)=>root.get(id)||'';
 const face=(ord:number)=>({id:`o1.1.f${ord}`,normalizedSelector:`o1.1.f${ord}`,selectorType:'face',occurrenceId:'o1.1',
   label:`Face o1.1.f${ord}`,pickData:{surfaceType:'plane',name:null,sourceName:null}});
 const {rerender}=render(<Chips references={[face(11)]} meshData={meshData} partName={partName}/>);
 expect(names()).toEqual(['l_bracket · face 11']);
 rerender(<Chips references={[face(11),face(12)]} meshData={meshData} partName={partName}/>);
 expect(names()).toEqual(['l_bracket · 2 faces']);
 cleanup();
 // A lone part with a name of its own keeps it; one with none and no file to go by is its occurrence.
 render(<Chips references={[face(3)]} meshData={{parts:[{id:'o1.1',occurrenceId:'o1.1',name:'sun_gear'}]}} partName={partName}/>);
 expect(names()).toEqual(['sun_gear · face 3']);
 cleanup();
 render(<Chips references={[face(3)]} meshData={meshData}/>);
 expect(names()).toEqual(['o1.1 · face 3']);
});

it("a chip's X drops its picks, and resting on it lights them: a face by its reference, a run or a part by its node",()=>{
 const onRemove=vi.fn(), onHover=vi.fn();
 const edges=[1,2].map(i=>({id:`o1.e${i}`,selectorType:'edge',normalizedSelector:`o1.e${i}`,occurrenceId:'o1',pickData:{curveType:'line',length:i}}));
 const face={id:'o2.f1',normalizedSelector:'o2.f1',selectorType:'face',occurrenceId:'o2',pickData:{surfaceType:'plane',area:3}};
 const part={id:'o3',nodeType:'part',name:'pin',leafPartIds:['o3'],children:[]};
 let chips:any[]=[];
 function Probe(){ chips=useStepReferenceChips({references:[...edges,face,part],onRemove,onHover}); return null; }
 render(<Probe/>);
 const [run,lone,pin]=chips;
 run.onRemove(); lone.onRemove(); pin.onRemove();
 expect(onRemove.mock.calls).toEqual([[['o1.e1','o1.e2']],[['o2.f1']],[['o3']]]);
 run.onHover(true); lone.onHover(true); pin.onHover(true); pin.onHover(false);
 expect(onHover.mock.calls).toEqual([[{nodeId:'o1'}],[{referenceId:'o2.f1'}],[{nodeId:'o3'}],[null]]);
});
