import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { AssetNodeDetail, AssetSyncResult, AssetTreeNode, AssetType } from '../models/asset-hierarchy.model';

@Injectable({ providedIn: 'root' })
export class AssetHierarchyService {
  private readonly baseUrl = 'http://localhost:8000/api/asset-hierarchy';

  constructor(private http: HttpClient) {}

  tree(): Observable<AssetTreeNode[]> {
    return this.http.get<AssetTreeNode[]>(`${this.baseUrl}/tree`);
  }

  /** Nodes are addressed by the record they stand for. */
  get(type: AssetType, sourceId: number): Observable<AssetNodeDetail> {
    return this.http.get<AssetNodeDetail>(`${this.baseUrl}/${type}/${sourceId}`);
  }

  /** Create or refresh nodes for every existing tenant, site and battery system. */
  sync(): Observable<AssetSyncResult> {
    return this.http.post<AssetSyncResult>(`${this.baseUrl}/sync`, {});
  }

  /** Removes the node only; the record stays and its children lose their parent. */
  delete(type: AssetType, sourceId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${type}/${sourceId}`);
  }
}
