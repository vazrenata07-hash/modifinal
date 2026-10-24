from pathlib import Path
import subprocess
import sys
import zipfile
import shutil

source = Path(sys.argv[1]).resolve()
apktool = Path(sys.argv[2]).resolve()
decoded = Path(sys.argv[3]).resolve()
work = Path(sys.argv[4]).resolve()
work.mkdir(parents=True, exist_ok=True)

urls = {
    'android.jar': 'https://repo.maven.apache.org/maven2/com/google/android/android/4.1.1.4/android-4.1.1.4.jar',
    'rxjava.jar': 'https://repo.maven.apache.org/maven2/io/reactivex/rxjava2/rxjava/2.2.21/rxjava-2.2.21.jar',
    'reactive.jar': 'https://repo.maven.apache.org/maven2/org/reactivestreams/reactive-streams/1.0.3/reactive-streams-1.0.3.jar',
    'r8.jar': 'https://dl.google.com/dl/android/maven2/com/android/tools/r8/8.3.37/r8-8.3.37.jar',
}
for name, url in urls.items():
    if not (work / name).exists():
        subprocess.run(['curl', '-fLsS', '--retry', '2', url, '-o', str(work / name)], check=True)

stubs = {
    'zc/f0.java': 'package zc; public class f0 { public static f0 a; public String n(){return null;} public String o(){return null;} }',
    'yb/h.java': '''package yb; public class h {
      public static h a;
      public interface a { void a(boolean success, String code, core.request.result.ActiveResult active, core.request.result.LoginResult login, String uri); }
      public void refreshSilently(a listener) {}
      public void c1(a listener) {}
    }''',
    'core/request/result/ActiveResult.java': 'package core.request.result; public class ActiveResult {}',
    'core/request/result/LoginResult.java': 'package core.request.result; public class LoginResult {}',
    'core/request/converterFactory/bean/ResultException.java': 'package core.request.converterFactory.bean; public class ResultException extends java.io.IOException {public ResultException(String code, String message){} public String getReturnCode(){return null;}}',
}
files = []
for name, content in stubs.items():
    path = work / 'stubs' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    files.append(str(path))
classes = work / 'classes'
shutil.rmtree(classes, ignore_errors=True)
classes.mkdir(exist_ok=True)
classpath = ':'.join(str(work / n) for n in ('android.jar', 'rxjava.jar', 'reactive.jar'))
subprocess.run(['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '8', '-target', '8', '-cp', classpath, '-d', str(classes), *files, str(source)], check=True)
with zipfile.ZipFile(work / 'helper.jar', 'w') as helper, zipfile.ZipFile(work / 'stubs.jar', 'w') as stubjar:
    for path in classes.rglob('*.class'):
        rel = str(path.relative_to(classes))
        target = helper if rel.startswith('com/interactive/brasiliptv/app/SilentRefresh') else stubjar
        target.write(path, rel)
dex = work / 'dex'
dex.mkdir(exist_ok=True)
java_home = Path(shutil.which('java')).resolve().parents[1]
subprocess.run(['java', '-cp', str(work / 'r8.jar'), 'com.android.tools.r8.D8', '--min-api', '21', '--lib', str(work / 'android.jar'), '--lib', str(java_home), '--classpath', str(work / 'rxjava.jar'), '--classpath', str(work / 'reactive.jar'), '--classpath', str(work / 'stubs.jar'), '--output', str(dex), str(work / 'helper.jar')], check=True)
helper_apk = work / 'helper-input.apk'
with zipfile.ZipFile(decoded.parent / 'original.apk') as original, zipfile.ZipFile(helper_apk, 'w') as package:
    for name in ('AndroidManifest.xml', 'resources.arsc'):
        package.writestr(name, original.read(name))
    package.write(dex / 'classes.dex', 'classes.dex')
helper_decoded = work / 'helper-decoded'
subprocess.run(['java', '-jar', str(apktool), 'd', '-r', '-f', str(helper_apk), '-o', str(helper_decoded)], check=True)
smali = helper_decoded / 'smali'
for stale in (decoded / 'smali/com/interactive/brasiliptv/app').glob('SilentRefresh*.smali'):
    stale.unlink()
for path in smali.rglob('*.smali'):
    rel = path.relative_to(smali)
    if not str(rel).startswith('com/interactive/brasiliptv/app/SilentRefresh'):
        raise RuntimeError('Unexpected helper class: ' + str(rel))
    target = decoded / 'smali' / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
print('Compiled helper classes injected; compile-time stubs excluded.')
