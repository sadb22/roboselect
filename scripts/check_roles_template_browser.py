from pathlib import Path
from playwright.sync_api import sync_playwright

out=Path(__file__).resolve().parent.parent/'test-results/ui'
out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    for width,height in ((1366,768),(390,844)):
        context=browser.new_context(viewport={'width':width,'height':height})
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:8765/')
        page.get_by_role('button',name='Вход как пользователь',exact=True).click()
        page.wait_for_url('**/legacy/')
        assert page.get_by_role('link',name='Ассортимент',exact=True).count()==0
        assert page.request.get('http://127.0.0.1:8765/workspace/').status==403
        assert page.request.post('http://127.0.0.1:8765/workspace/parser/').status==403
        page.goto('http://127.0.0.1:8765/studies/new/')
        page.wait_for_url('**/studies/new/')
        csv=page.request.get('http://127.0.0.1:8765/studies/template/').body()
        page.locator('[name=project_name]').fill('Проверка загрузки шаблона')
        page.locator('[name=file]').set_input_files({'name':'warehouse.csv','mimeType':'text/csv','buffer':csv})
        page.get_by_role('button',name='Загрузить данные в форму',exact=True).click()
        page.get_by_text('Данные из шаблона загружены в форму.',exact=False).wait_for()
        assert page.locator('[name=project_name]').input_value()=='Проверка загрузки шаблона'
        assert page.locator('[name=area]').input_value()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(out/f'warehouse-template-{width}.png'))
        page.goto('http://127.0.0.1:8765/')
        page.get_by_role('button',name='Вход как администратор',exact=True).click()
        page.wait_for_url('**/workspace/robots/')
        assert page.get_by_role('link',name='Ассортимент',exact=True).count()==1
        page.goto('http://127.0.0.1:8765/')
        page.get_by_role('button',name='Вход как пользователь',exact=True).click()
        page.wait_for_url('**/legacy/')
        assert page.request.get('http://127.0.0.1:8765/workspace/robots/').status==403
        assert not errors,errors
        print(f'{width}x{height}: role switching, access denial and CSV preview OK')
        context.close()
    browser.close()
