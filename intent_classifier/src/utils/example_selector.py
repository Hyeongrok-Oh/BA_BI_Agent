import json
import numpy as np
import os
from openai import OpenAI

class ExampleSelector:
    def __init__(self, examples_path):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.examples = self._load_examples(examples_path)
        # Cache embeddings to avoid re-calculating (in production, use a Vector DB)
        self.embeddings = self._precompute_embeddings()

    def _load_examples(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def _get_embedding(self, text):
        text = text.replace("\n", " ")
        return self.client.embeddings.create(input=[text], model="text-embedding-3-small").data[0].embedding

    def _precompute_embeddings(self):
        embeddings = []
        for ex in self.examples:
            # Embed the QUESTION as the key for similarity
            embeddings.append(self._get_embedding(ex["question"]))
        return embeddings

    def _cosine_similarity(self, vec1, vec2):
        """Calculate cosine similarity between two vectors."""
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return np.dot(vec1, vec2) / (norm1 * norm2)

    def find_similar_examples(self, query, k=3):
        """Original method for backward compatibility."""
        if not self.examples:
            return []
            
        query_embedding = self._get_embedding(query)
        
        similarities = []
        for idx, emb in enumerate(self.embeddings):
            similarity = self._cosine_similarity(query_embedding, emb)
            similarities.append((similarity, self.examples[idx]))
        
        similarities.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in similarities[:k]]

    def find_diverse_examples(self, query, k=3, ensure_category_diversity=True, min_similarity=0.4):
        """
        Find k examples with category diversity guarantee.
        
        Algorithm:
        1. Calculate similarities for all examples
        2. Filter by minimum similarity threshold (with fallback)
        3. Group by category
        4. Round-robin select from each category
        
        Args:
            query: User query string
            k: Number of examples to return
            ensure_category_diversity: If True, use Round-Robin; else top-k
            min_similarity: Minimum similarity threshold (default 0.4, fallback to 0.3)
        
        Returns:
            List of k diverse examples
        """
        if not self.examples:
            return []
        
        query_embedding = self._get_embedding(query)
        
        # Calculate similarities with category info
        all_similarities = []
        for idx, emb in enumerate(self.embeddings):
            sim = self._cosine_similarity(query_embedding, emb)
            all_similarities.append({
                'similarity': sim,
                'example': self.examples[idx],
                'category': self.examples[idx].get('category', 'Unknown')
            })
        
        # Filter by minimum similarity threshold
        filtered = [s for s in all_similarities if s['similarity'] >= min_similarity]
        
        # Fallback: if not enough examples, lower threshold to 0.3
        if len(filtered) < k and min_similarity > 0.3:
            filtered = [s for s in all_similarities if s['similarity'] >= 0.3]
        
        if not ensure_category_diversity or not filtered:
            # Simple top-k fallback
            all_similarities.sort(key=lambda x: x['similarity'], reverse=True)
            return [s['example'] for s in all_similarities[:k]]
        
        # Group by category and sort within each group
        category_groups = {}
        for item in filtered:
            cat = item['category']
            if cat not in category_groups:
                category_groups[cat] = []
            category_groups[cat].append(item)
        
        for cat in category_groups:
            category_groups[cat].sort(key=lambda x: x['similarity'], reverse=True)
        
        # Round-robin selection
        selected = []
        category_keys = list(category_groups.keys())
        cat_pointers = {cat: 0 for cat in category_keys}
        cat_idx = 0
        
        while len(selected) < k and category_keys:
            current_cat = category_keys[cat_idx % len(category_keys)]
            pointer = cat_pointers[current_cat]
            
            if pointer < len(category_groups[current_cat]):
                selected.append(category_groups[current_cat][pointer]['example'])
                cat_pointers[current_cat] += 1
                cat_idx += 1
            else:
                # This category exhausted, remove from rotation
                category_keys.remove(current_cat)
                if not category_keys:
                    break
                # Don't increment cat_idx, try next category
        
        return selected
