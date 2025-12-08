import chromadb
from chromadb.utils import embedding_functions
import os
import pandas as pd
import uuid


class MemoryEngine:
    def __init__(self, db_path="trade_memory_db"):
        # 锁定数据库路径到项目目录
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.persist_path = os.path.join(base_dir, db_path)
        
        # 初始化 Chroma 客户端 (持久化存储)
        self.client = chromadb.PersistentClient(path=self.persist_path)
        
        # 使用默认的轻量级 Embedding 模型 (all-MiniLM-L6-v2)
        # 第一次运行会自动下载模型 (约80MB)，完全本地运行，免费
        self.emb_fn = embedding_functions.DefaultEmbeddingFunction()
        
        # 创建或获取集合 (Collection)
        self.collection = self.client.get_or_create_collection(
            name="trading_notes",
            embedding_function=self.emb_fn
        )
        print(f"记忆引擎已启动: {self.persist_path}")

    def add_trade_memory(self, trade_id, note, symbol, strategy, mental_state, pnl, mae, mfe):
        """
        将一笔交易的复盘笔记存入向量库
        """
        if not note or len(note) < 5:
            return False, "笔记太短，无需记忆"
            
        try:
            # 构造元数据 (Metadata)，方便以后按条件筛选
            # 注意：Chroma 的 metadata 值必须是 str, int, float, bool
            meta = {
                "symbol": str(symbol),
                "strategy": str(strategy),
                "mental_state": str(mental_state),
                "pnl": float(pnl),
                "mae": float(mae) if mae is not None else 0.0,
                "mfe": float(mfe) if mfe is not None else 0.0,
                "date": pd.Timestamp.now().strftime('%Y-%m-%d')
            }
            
            # 存入数据库
            # ID 使用 trade_id，确保不重复添加
            self.collection.upsert(
                documents=[note],
                metadatas=[meta],
                ids=[str(trade_id)]
            )
            return True, "✅ 笔记已写入大脑皮层"
        except Exception as e:
            return False, f"记忆写入失败: {str(e)}"

    def retrieve_similar_memories(self, query_text, n_results=3):
        """
        根据当前情境，回想过去相似的案例
        """
        try:
            if not query_text:
                return []
                
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results
            )
            
            # 解析结果
            memories = []
            if results['documents']:
                docs = results['documents'][0]
                metas = results['metadatas'][0]
                
                for i in range(len(docs)):
                    memories.append({
                        "note": docs[i],
                        "meta": metas[i]
                    })
            return memories
            
        except Exception as e:
            print(f"记忆检索失败: {e}")
            return []


# 测试代码
if __name__ == "__main__":
    me = MemoryEngine()
    # 模拟存入
    me.add_trade_memory("test_001", "千万不要追涨，特别是背离的时候", "BTCUSDT", "突破", "FOMO", -100, -2.5, 0.5)
    # 模拟检索
    res = me.retrieve_similar_memories("我想追涨")
    print("检索结果:", res)

