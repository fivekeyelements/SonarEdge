"""Build our small MusicBee plugin with Windows' .NET Framework compiler."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'musicbee/mb_SonarEdge.dll'

def build():
    compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/target:library', '/optimize+',
                    '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
                    '/out:' + str(OUTPUT), str(ROOT / 'musicbee/SonarEdgePlugin.cs')], check=True)
    return OUTPUT

if __name__ == '__main__':
    print(build())
