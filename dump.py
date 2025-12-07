import os
import re
import fnmatch

def should_exclude(file_path):
    """
    指定されたファイルパスが除外対象かどうかを判定する
    """
    # 除外パターンのリスト
    exclude_patterns = [
        # Pythonバイトコード
        "__pycache__/*", "*.py[cod]", "*$py.class",
        # 環境設定ファイル
        ".env", "*.json", ".venv/*", "venv/*", "result/*", "ENV/*", "env.bak/*", "env/*",
        # pip環境設定ファイル
        "pip-log.txt", "pip-delete-this-directory.txt",
        # コンパイル成果物
        "*.egg-info/*", "*.egg", "*.eggs", "*.whl","*.git",".git",
        # テストカバレッジレポート
        "htmlcov/*", ".tox/*", ".nox/*", ".coverage", "coverage.*", ".cache",
        "nosetests.xml", "coverage.xml", "*.cover", "*.py,cover",
        # Jupyter Notebookのチェックポイント
        ".ipynb_checkpoints/*",
        # pylint, mypyなどの設定
        ".mypy_cache/*", ".pyre/*", ".pytype/*", ".pyright/*",
        # IDEやエディタの設定ファイル
        ".vscode/*", ".idea/*", "*.sublime-workspace", "*.sublime-project",
        # MacやLinuxのシステムファイル
        ".DS_Store", "*.swp", "*~",
        # パッケージ管理ツールの成果物
        "poetry.lock", "Pipfile.lock",
        # Vercelキャッシュ
        ".vercel/*", "*/.vercel/*",
        # Docker関連
        "docker-compose.override.yml", ".dockerignore",
        # その他
        "*.log", "*.pot", "*.mo", "cline_log.txt", "git_tracking_status.txt",
        # 本番環境用秘密ファイル
        "*.pem", ".secrets", ".env.act",
        # 出力ファイル自体を除外
        "dump_result.txt"
    ]
    
    # ファイル名のみを取得
    file_name = os.path.basename(file_path)
    
    # ディレクトリパスを含む相対パス
    rel_path = file_path
    
    # 除外パターンとマッチするかチェック
    for pattern in exclude_patterns:
        # ファイル名だけでマッチングを試みる
        if fnmatch.fnmatch(file_name, pattern):
            return True
        
        # パスを含めたマッチングも試みる
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        
        # __pycache__ ディレクトリ内のファイルを除外
        if "__pycache__" in rel_path:
            return True

    # .git 配下は丸ごと除外
    if rel_path.startswith(".git") or "/.git/" in rel_path:
        return True
    # .vecel 配下は丸ごと除外
    if rel_path.startswith(".vecel") or "/.vecel/" in rel_path:
        return True
    
    return False

def dump_files_to_txt(target_dir):
    """
    指定されたディレクトリ内のファイルを走査し、内容をdump_result.txtに出力する
    除外リストに含まれるファイルはスキップする
    フォルダとファイルはアルファベット順にソートされる
    """
    # 出力ファイルのパスを指定されたディレクトリ内に設定
    output_file = os.path.join(target_dir, "dump_result.txt")
    
    # 相対パスの基準となるディレクトリ
    base_dir = target_dir
    
    # ファイルパスを収集してソートする
    all_files = []
    for root, dirs, files in os.walk(target_dir):
        # .git など除外ディレクトリを辿らないようフィルタ
        dirs[:] = [d for d in dirs if not should_exclude(os.path.relpath(os.path.join(root, d), start=base_dir))]
        # ディレクトリをアルファベット順にソート
        dirs.sort()
        # ファイルをアルファベット順にソート
        for fname in sorted(files):
            abs_path = os.path.join(root, fname)
            
            # 出力ファイル自体はスキップ
            if abs_path == output_file:
                continue
            
            # 除外対象のファイルはスキップ
            rel_path = os.path.relpath(abs_path, start=base_dir)
            if should_exclude(rel_path):
                continue
            
            all_files.append((rel_path, abs_path))
    
    # ファイルをアルファベット順にソート
    all_files.sort()
    
    with open(output_file, "w", encoding="utf-8") as out:
        for rel_path, abs_path in all_files:
            out.write(f"/{rel_path}:\n")
            out.write("-" * 80 + "\n")
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        out.write(f"{i:3} | {line.rstrip()}\n")
            except Exception as e:
                out.write(f"[ERROR READING FILE]: {e}\n")
            out.write("-" * 80 + "\n\n")

if __name__ == "__main__":
    # コマンドライン引数を使わず、直接変数に値を設定
    # target_directory = "/Users/neromehiro/hiro folder/my_Works/programing/aimsales-api/module/b_AddCompany"
    target_directory = "/Users/neromehiro/hiro folder/my_Works/programing/makers_release"
    dump_files_to_txt(target_directory)
    print(f"✅ 出力完了: {target_directory}/dump_result.txt")
