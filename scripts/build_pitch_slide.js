const pptxgen = require('pptxgenjs');
const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE'; // 13.33 x 7.5
const s = pres.addSlide();
s.background = { color: 'FFFFFF' };
const NAVY='14213D', TEAL='0F766E', MINT='D9F2EC', INK='1F2937', MUTED='5B6576', AMBER='B45309', SOFT='F3F6FA';
const F='Calibri', H='Cambria';

// Title band (dark)
s.addShape(pres.shapes.RECTANGLE,{x:0,y:0,w:13.33,h:1.25,fill:{color:NAVY},line:{color:NAVY}});
s.addText([{text:'LendSprint',options:{bold:true,fontSize:30,color:'FFFFFF',fontFace:H}},
  {text:'   AI credit-underwriting copilot for MSME lending',options:{fontSize:18,color:'CADCFC',fontFace:F}}],
  {x:0.5,y:0.18,w:12.3,h:0.6,margin:0,isTextBox:true});
s.addText('Problem chosen: "How can financial institutions make better lending decisions using complex or incomplete information?"  ·  User: MSME credit officer',
  {x:0.5,y:0.78,w:12.3,h:0.36,margin:0,fontSize:12.5,color:'E5ECF8',fontFace:F,italic:true,isTextBox:true});

// Column helpers
function card(x,y,w,h,fill){ s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x,y,w,h,rectRadius:0.08,fill:{color:fill},line:{color:fill}}); }
function head(x,y,w,t,color){ s.addText(t,{x,y,w,h:0.4,margin:0,fontSize:17,bold:true,color:color||NAVY,fontFace:H,isTextBox:true}); }
function bullets(x,y,w,h,items,size){
  s.addText(items.map((t,i)=>({text:t,options:{bullet:true,breakLine:i<items.length-1,paraSpaceAfter:5}})),
    {x,y,w,h,margin:0,fontSize:size||12.5,color:INK,fontFace:F,valign:'top',isTextBox:true});
}

// 1. Why
card(0.45,1.5,3.85,4.6,SOFT);
head(0.65,1.62,3.5,'Why this problem');
bullets(0.65,2.1,3.5,3.9,[
  'Credit officers read bank statements, ITRs and GST returns by hand and re-key numbers into spreadsheets.',
  'Mismatches between documents (GST vs banked turnover, hidden EMIs, bounces) are easy to miss.',
  'Slow turnaround loses good borrowers; inconsistent calls raise risk.',
  'Decisions are hard to explain to a credit committee or auditor.',
  'Generic "AI scoring" is a black box regulated lenders cannot defend.'],12.5);

// 2. How AI is used - pipeline
head(4.6,1.55,5.2,'How it works: AI where it adds judgement');
const steps=[
  ['AI','Classify each PDF (bank / ITR / GST)'],
  ['AI','Extract fields with verbatim evidence + confidence; read and classify every bank transaction by meaning'],
  ['Check','Verify evidence against the PDF; reconcile every row to the running balance'],
  ['Check','Cross-document contradictions + transparent credit policy (FOIR, DSCR, bounces, ABB)'],
  ['AI','Credit memo: grade, risks citing evidence ids, conditions, borrower questions'],
  ['Gate','AI can never auto-approve a failed rule or critical flag → capped at Refer'],
  ['Human','Officer decides; overrides need justification; full audit + Ask-Brain chat'],
];
steps.forEach(([tag,t],i)=>{
  const y=2.02+i*0.58;
  const col = tag==='AI'?TEAL: tag==='Human'?'6D28D9': tag==='Gate'?AMBER:'475569';
  s.addShape(pres.shapes.ROUNDED_RECTANGLE,{x:4.6,y:y+0.04,w:0.78,h:0.36,rectRadius:0.06,fill:{color:col},line:{color:col}});
  s.addText(tag,{x:4.6,y:y+0.04,w:0.78,h:0.36,margin:0,align:'center',valign:'middle',fontSize:11,bold:true,color:'FFFFFF',fontFace:F,isTextBox:true});
  s.addText(t,{x:5.5,y:y-0.02,w:4.35,h:0.52,margin:0,valign:'middle',fontSize:11.5,color:INK,fontFace:F,isTextBox:true});
});

// 3. Tech + next
card(10.1,1.5,2.8,2.38,MINT);
head(10.28,1.6,2.5,'Key tech choices',TEAL);
bullets(10.28,2.05,2.5,1.85,[
  'LLM-agnostic (Gemini / Claude / GPT)',
  'FastAPI + SQLite, no-build web UI',
  'pdfplumber keeps table structure',
  'Deterministic checks audit the LLM'],11.5);
card(10.1,4.0,2.8,2.1,SOFT);
head(10.28,4.08,2.5,'Next with more time');
bullets(10.28,4.5,2.5,1.5,[
  'OCR / vision for scanned docs',
  'Account Aggregator, bureau, GST APIs',
  'PD model on lender outcome data',
  'Policy versioning, maker-checker'],11);

// Footer: demo proof + assumptions
s.addText([
  {text:'Demo: ',options:{bold:true,color:NAVY}},
  {text:'3 synthetic MSME borrowers: a clean file · GST turnover 28% above banked receipts · critical contradictions with 4 bounces and an undisclosed NBFC loan. A missing ITR blocks the decision.',options:{color:INK}}],
  {x:0.45,y:6.28,w:12.45,h:0.42,margin:0,fontSize:11.5,fontFace:F,isTextBox:true});
s.addText('Assumptions: text-based PDFs; business credits = customer receipts + cash deposits; income = ITR net profit / 12; policy thresholds illustrative. All borrowers and documents are synthetic. No real customer data used.',
  {x:0.45,y:6.72,w:12.45,h:0.5,margin:0,fontSize:10,italic:true,color:MUTED,fontFace:F,isTextBox:true});
s.addNotes('Walk the pipeline top to bottom. Emphasise that every number shown comes from the uploaded PDFs, the LLM is checked by deterministic verification, and the human signs off.');
pres.writeFile({fileName:'/home/claude/lendsprint-ai/docs/LendSprint_pitch_slide.pptx'}).then(()=>console.log('ok'));
