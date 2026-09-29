"""Reproduce the public synthetic example and current deployment documentation."""
import os
import sys
import json
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.utils import timezone
from workflow.domain import default_requirements
from workflow.finance import defaults
from workflow.views import catalog_snapshot
from workflow.selection import suggest
from workflow import reports
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
from reportlab.lib.styles import ParagraphStyle

out=root/'output/workflow';out.mkdir(parents=True,exist_ok=True)
req=default_requirements();fin=defaults();snap=catalog_snapshot()
choices,_=suggest(req,fin,{k:v for k,v in snap.items() if v.get('demo')})
if not choices:raise SystemExit('Initialize the demo catalogue before export')
assignments,result=choices[0]
c=SimpleNamespace(pk='DEMO',version=SimpleNamespace(study=SimpleNamespace(name='Типовой склад. Синтетический пример'),number=1,requirements=req,finance=fin),assignments=assignments,result=result,created_at=timezone.now(),snapshot={str(a['revision']):snap[a['revision']] for a in assignments})
(out/'sample-report.pdf').write_bytes(reports.pdf(c))
(out/'sample-report.xlsx').write_bytes(reports.xlsx(c))
(out/'sample-report.json').write_text(json.dumps(dict(model='workflow-2.1',requirements=req,finance=fin,assignments=assignments,catalog=c.snapshot,result=result,calculated_at=c.created_at.isoformat()),ensure_ascii=False,indent=2))
body=ParagraphStyle('body',fontName='WorkflowRu',fontSize=10,leading=15,spaceAfter=8)
heading=ParagraphStyle('heading',parent=body,fontSize=15,leading=20,spaceBefore=12,spaceAfter=10,keepWithNext=True)
title=ParagraphStyle('title',parent=body,fontSize=24,leading=29,spaceAfter=20)
story=[]
for line in (root/'docs/WORKFLOW_GUIDE.md').read_text().splitlines():
    if not line.strip():continue
    style=title if line.startswith('# ') else heading if line.startswith('## ') else body
    text=line.lstrip('# ').replace('`','')
    story.append(Paragraph(escape(text),style))
def footer(canvas,doc):
    canvas.setFont('WorkflowRu',8);canvas.drawString(42,22,'Робоскоп. Документация конкурсного прототипа');canvas.drawRightString(552,22,str(doc.page))
SimpleDocTemplate(str(out/'documentation.pdf'),leftMargin=42,rightMargin=42,topMargin=38,bottomMargin=40,title='Робоскоп: документация').build(story,onFirstPage=footer,onLaterPages=footer)
print(json.dumps(dict(files=[p.name for p in out.iterdir()],scenarios=[{'mode':s['mode'],'tco':s['tco']} for s in result['scenarios']]),ensure_ascii=False))
